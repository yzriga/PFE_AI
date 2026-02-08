"""
Django management command for running RAG evaluation.

Usage:
    python manage.py run_eval --topic "transformers" --n-papers 10 --n-questions 20
    
This command will:
1. Fetch papers from arXiv on specified topic
2. Import them into a test session
3. Generate diverse evaluation questions
4. Execute queries and log metrics
5. Display performance summary
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
import arxiv
import time
import logging

from rag.models import Session, Document, Question
from rag.services.arxiv_service import ArxivService
from rag.services.metrics_service import MetricsService
from rag.query import ask_with_citations
from langchain_ollama import OllamaLLM

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run RAG evaluation by fetching papers, generating questions, and measuring performance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--topic',
            type=str,
            required=True,
            help='Research topic to search for (e.g., "transformers", "reinforcement learning")'
        )
        parser.add_argument(
            '--n-papers',
            type=int,
            default=10,
            help='Number of papers to fetch and import (default: 10)'
        )
        parser.add_argument(
            '--n-questions',
            type=int,
            default=20,
            help='Number of evaluation questions to generate and test (default: 20)'
        )
        parser.add_argument(
            '--session',
            type=str,
            default=None,
            help='Session name to use (default: auto-generated from topic)'
        )
        parser.add_argument(
            '--skip-import',
            action='store_true',
            help='Skip paper import (assumes session already has documents)'
        )

    def handle(self, *args, **options):
        topic = options['topic']
        n_papers = options['n_papers']
        n_questions = options['n_questions']
        session_name = options['session'] or f"eval_{topic.replace(' ', '_')}_{int(time.time())}"
        skip_import = options['skip_import']
        
        self.stdout.write(self.style.SUCCESS(
            f"\n{'='*60}\n"
            f"RAG Evaluation Run\n"
            f"{'='*60}\n"
            f"Topic: {topic}\n"
            f"Session: {session_name}\n"
            f"Papers to fetch: {n_papers}\n"
            f"Questions to test: {n_questions}\n"
            f"{'='*60}\n"
        ))
        
        try:
            # Step 1: Create or get session
            session, created = Session.objects.get_or_create(name=session_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f"✓ Created session: {session_name}"))
            else:
                self.stdout.write(self.style.WARNING(f"⚠ Using existing session: {session_name}"))
            
            if not skip_import:
                # Step 2: Fetch and import papers
                self.stdout.write("\nFetching papers from arXiv...")
                papers = self._fetch_arxiv_papers(topic, n_papers)
                
                if not papers:
                    raise CommandError(f"No papers found for topic '{topic}'")
                
                self.stdout.write(self.style.SUCCESS(f"✓ Found {len(papers)} papers"))
                
                # Step 3: Import papers
                self.stdout.write("\nImporting papers...")
                imported_count = self._import_papers(session, papers)
                self.stdout.write(self.style.SUCCESS(
                    f"✓ Successfully imported {imported_count}/{len(papers)} papers"
                ))
            else:
                # Check if session has documents
                doc_count = Document.objects.filter(session=session, status='INDEXED').count()
                if doc_count == 0:
                    raise CommandError(f"Session '{session_name}' has no indexed documents")
                self.stdout.write(self.style.WARNING(
                    f"⚠ Skipping import, using {doc_count} existing documents"
                ))
            
            # Wait for indexing to complete
            self._wait_for_indexing(session)
            
            # Step 4: Generate evaluation questions
            self.stdout.write("\nGenerating evaluation questions...")
            questions = self._generate_questions(topic, n_questions)
            self.stdout.write(self.style.SUCCESS(f"✓ Generated {len(questions)} questions"))
            
            # Step 5: Run queries and measure
            self.stdout.write("\nRunning evaluation queries...")
            results = self._run_queries(session, questions)
            
            # Step 6: Display summary
            self._display_summary(session, results)
            
            self.stdout.write(self.style.SUCCESS(
                f"\n{'='*60}\n"
                f"Evaluation Complete!\n"
                f"Session: {session_name}\n"
                f"View detailed metrics: /api/metrics/summary/\n"
                f"{'='*60}\n"
            ))
            
        except Exception as e:
            raise CommandError(f"Evaluation failed: {str(e)}")
    
    def _fetch_arxiv_papers(self, topic: str, n_papers: int) -> list:
        """Fetch papers from arXiv API."""
        search = arxiv.Search(
            query=topic,
            max_results=n_papers,
            sort_by=arxiv.SortCriterion.Relevance
        )
        
        papers = []
        for result in search.results():
            papers.append({
                'arxiv_id': result.entry_id.split('/')[-1],
                'title': result.title,
                'authors': ', '.join([a.name for a in result.authors]),
                'abstract': result.summary,
                'pdf_url': result.pdf_url
            })
        
        return papers
    
    def _import_papers(self, session: Session, papers: list) -> int:
        """Import papers into session using ArxivService."""
        arxiv_service = ArxivService()
        imported_count = 0
        
        for i, paper in enumerate(papers, 1):
            try:
                self.stdout.write(f"  [{i}/{len(papers)}] Importing: {paper['title'][:50]}...")
                
                # Import using ArxivService
                arxiv_service.import_paper(
                    arxiv_id=paper['arxiv_id'],
                    session_name=session.name
                )
                
                imported_count += 1
                self.stdout.write(self.style.SUCCESS(f"    ✓ Imported"))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"    ✗ Failed: {str(e)}"))
                continue
            
            # Rate limiting
            time.sleep(1)
        
        return imported_count
    
    def _wait_for_indexing(self, session: Session):
        """Wait for all documents in session to be indexed."""
        self.stdout.write("\nWaiting for indexing to complete...")
        
        max_wait = 300  # 5 minutes
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            pending = Document.objects.filter(
                session=session,
                status__in=['UPLOADED', 'PROCESSING']
            ).count()
            
            if pending == 0:
                self.stdout.write(self.style.SUCCESS("✓ All documents indexed"))
                return
            
            self.stdout.write(f"  {pending} documents still processing...")
            time.sleep(5)
        
        raise CommandError("Timeout waiting for indexing to complete")
    
    def _generate_questions(self, topic: str, n_questions: int) -> list:
        """Generate diverse evaluation questions using LLM."""
        llm = OllamaLLM(model="mistral")
        
        prompt = f"""Generate {n_questions} diverse research questions about {topic}.

The questions should:
1. Cover different aspects (theory, methods, applications, comparisons)
2. Vary in complexity (simple factual to complex analytical)
3. Be suitable for testing a RAG system on scientific papers
4. Be answerable from scientific literature

Return ONLY a numbered list of questions, one per line:
1. Question one here
2. Question two here
...
"""
        
        response = llm.invoke(prompt)
        
        # Parse questions from response
        questions = []
        for line in response.split('\n'):
            line = line.strip()
            # Match lines starting with number and period
            if line and line[0].isdigit() and '.' in line:
                # Extract question after number
                question = line.split('.', 1)[1].strip()
                if question:
                    questions.append(question)
        
        # Fallback: if parsing failed, generate basic questions
        if len(questions) < n_questions // 2:
            questions = [
                f"What are the main challenges in {topic}?",
                f"What are the state-of-the-art methods in {topic}?",
                f"How has {topic} evolved over time?",
                f"What are common applications of {topic}?",
                f"What are the limitations of current {topic} approaches?",
                f"What future directions are proposed for {topic}?",
                f"How do different {topic} methods compare?",
                f"What datasets are commonly used for {topic}?",
                f"What evaluation metrics are used in {topic}?",
                f"What are the theoretical foundations of {topic}?",
            ][:n_questions]
        
        return questions[:n_questions]
    
    def _run_queries(self, session: Session, questions: list) -> list:
        """Run queries and collect results."""
        results = []
        
        for i, question_text in enumerate(questions, 1):
            self.stdout.write(f"  [{i}/{len(questions)}] {question_text[:60]}...")
            
            try:
                start_time = time.time()
                
                # Execute query (metrics logged automatically via integrated logging)
                result = ask_with_citations(
                    question=question_text,
                    session_name=session.name,
                    sources=None
                )
                
                latency = int((time.time() - start_time) * 1000)
                
                results.append({
                    'question': question_text,
                    'success': True,
                    'latency_ms': latency,
                    'citations': len(result.get('citations', []))
                })
                
                self.stdout.write(self.style.SUCCESS(
                    f"    ✓ {latency}ms, {len(result.get('citations', []))} citations"
                ))
                
            except Exception as e:
                results.append({
                    'question': question_text,
                    'success': False,
                    'error': str(e)
                })
                self.stdout.write(self.style.ERROR(f"    ✗ Error: {str(e)}"))
        
        return results
    
    def _display_summary(self, session: Session, results: list):
        """Display evaluation summary."""
        total = len(results)
        successful = sum(1 for r in results if r.get('success', False))
        failed = total - successful
        
        latencies = [r['latency_ms'] for r in results if r.get('success', False)]
        avg_latency = sum(latencies) // len(latencies) if latencies else 0
        min_latency = min(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0
        
        total_citations = sum(r.get('citations', 0) for r in results if r.get('success', False))
        avg_citations = total_citations / successful if successful > 0 else 0
        
        self.stdout.write(
            f"\n{'='*60}\n"
            f"Evaluation Summary\n"
            f"{'='*60}\n"
            f"Queries:\n"
            f"  Total:      {total}\n"
            f"  Successful: {successful} ({successful/total*100:.1f}%)\n"
            f"  Failed:     {failed}\n"
            f"\n"
            f"Latency (ms):\n"
            f"  Average: {avg_latency}\n"
            f"  Min:     {min_latency}\n"
            f"  Max:     {max_latency}\n"
            f"\n"
            f"Citations:\n"
            f"  Total:   {total_citations}\n"
            f"  Average: {avg_citations:.1f} per query\n"
            f"{'='*60}\n"
        )
        
        # Use MetricsService to get detailed stats from DB
        metrics_service = MetricsService()
        session_history = metrics_service.get_session_history(session, limit=total)
        
        if session_history:
            self.stdout.write(
                f"\n✓ {len(session_history)} queries logged to database\n"
                f"  View via: /api/metrics/summary/\n"
            )
