import time

from django.core.management.base import BaseCommand

from rag.services.ingestion_jobs import IngestionJobRunner


class Command(BaseCommand):
    help = "Process queued ingestion jobs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process available jobs once and exit.")
        parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds to wait when the queue is empty.")
        parser.add_argument("--max-jobs", type=int, default=0, help="Maximum number of jobs to process before exiting. 0 means unlimited.")

    def handle(self, *args, **options):
        runner = IngestionJobRunner()
        processed = 0

        while True:
            job = runner.process_next_job()
            if job is not None:
                processed += 1
                self.stdout.write(f"processed job {job.id} status={job.status}")
                if options["max_jobs"] and processed >= options["max_jobs"]:
                    break
                continue

            if options["once"]:
                break

            time.sleep(options["poll_interval"])
