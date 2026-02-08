# 📝 Journal des Modifications - Scientific Research Navigator

Ce document retrace toutes les modifications apportées au système, avec explications techniques et justifications.

---

## 📅 8 Février 2026

### 🎯 D0: Audit d'Architecture

**Objectif**: Documenter l'état actuel du système et planifier l'évolution vers NotebookLM-like

#### Fichiers créés
- **ARCHITECTURE.md** (500+ lignes)

#### Contenu
```
✓ Audit complet des modèles Django
✓ Inventaire des endpoints API existants
✓ Documentation du pipeline RAG actuel
✓ Identification des gaps techniques
✓ Roadmap détaillée en 7 phases (D0-D7)
✓ Timeline de 20 jours avec estimations
```

#### Justification
- Besoin de comprendre la base de code avant d'ajouter des fonctionnalités complexes
- Documentation nécessaire pour les futurs développeurs
- Plan structuré pour éviter la dette technique

---

### 🎯 D1: Pipeline d'Ingestion Unifié Asynchrone

**Objectif**: Remplacer l'upload synchrone bloquant (30-60s timeout) par un système asynchrone avec suivi d'état

#### 🔧 Modifications Backend

##### 1. **Modèle Document** (`backend/rag/models.py`)
**Ajout de 4 nouveaux champs**:
```python
status = models.CharField(
    max_length=20,
    choices=[
        ('UPLOADED', 'Uploaded'),
        ('PROCESSING', 'Processing'),
        ('INDEXED', 'Indexed'),
        ('FAILED', 'Failed'),
    ],
    default='UPLOADED'
)
processing_started_at = models.DateTimeField(null=True, blank=True)
processing_completed_at = models.DateTimeField(null=True, blank=True)
error_message = models.TextField(null=True, blank=True)
```

**Pourquoi ?**
- Tracking précis de l'état de chaque document
- Permet au frontend de poller l'état sans bloquer
- Capture des erreurs pour debugging
- Métriques de performance (temps de traitement)

##### 2. **Service d'Ingestion** (`backend/rag/services/ingestion.py`)
**Nouvelle classe**: `IngestionService`

**Méthodes principales**:
```python
def ingest_document(self, document_id: int, pdf_path: str) -> bool:
    """
    Pipeline complet d'ingestion avec:
    - Logging détaillé à chaque étape
    - Gestion d'erreurs robuste (try/except)
    - Mise à jour automatique des status
    - Extraction métadonnées + chunking + indexation Chroma
    """

def reingest_document(self, document_id: int, pdf_path: str) -> bool:
    """
    Retry pour documents FAILED:
    - Reset du status à UPLOADED
    - Nettoyage des anciennes erreurs
    - Relance de l'ingestion complète
    """
```

**Avantages**:
- Séparation des responsabilités (SRP)
- Code testable isolément
- Réutilisable (upload manuel vs arXiv import vs PubMed)
- Logs centralisés

##### 3. **Vue Upload Asynchrone** (`backend/rag/views.py`)
**Avant** (bloquant):
```python
def upload_pdf(request):
    # Sauvegarde du fichier
    # Ingestion synchrone (30-60s) ❌
    ingest.ingest_pdf(...)
    return Response(status=201)  # Après 60s
```

**Après** (non-bloquant):
```python
def upload_pdf(request):
    # 1. Sauvegarde du fichier
    # 2. Création du Document avec status=UPLOADED
    
    # 3. Lancement du thread background
    def ingest_in_background():
        service = IngestionService()
        service.ingest_document(document.id, str(full_path))
    
    thread = threading.Thread(target=ingest_in_background, daemon=True)
    thread.start()
    
    # 4. Retour IMMEDIAT (< 100ms)
    return Response({
        "message": "PDF upload initiated. Processing in background.",
        "document_id": document.id,
        "status": "UPLOADED"
    }, status=202)  # 202 Accepted ✅
```

**Bénéfices**:
- UX améliorée: pas de timeout frontend
- Scalabilité: peut traiter plusieurs uploads simultanément
- Robustesse: échec d'un document n'affecte pas les autres
- RESTful: 202 Accepted = "requête acceptée, traitement asynchrone"

##### 4. **Endpoint de Status** (`backend/rag/views.py` + `urls.py`)
**Nouveau endpoint**: `GET /api/documents/<id>/status/`

**Réponse**:
```json
{
  "document_id": 1,
  "filename": "paper.pdf",
  "session": "yahia",
  "status": "INDEXED",
  "uploaded_at": "2026-02-08T20:13:57Z",
  "processing_started_at": "2026-02-08T20:13:57Z",
  "processing_completed_at": "2026-02-08T20:13:58Z",
  "processing_time_seconds": 1.55,
  "error_message": null,
  "metadata": {
    "title": "...",
    "abstract": "...",
    "page_count": 14
  }
}
```

**Usage**:
```javascript
// Frontend polling pattern
async function pollStatus(documentId) {
  while (true) {
    const response = await fetch(`/api/documents/${documentId}/status/`);
    const data = await response.json();
    
    if (data.status === 'INDEXED') {
      showSuccess('Document ready for queries!');
      break;
    } else if (data.status === 'FAILED') {
      showError(data.error_message);
      break;
    }
    
    await sleep(2000); // Poll toutes les 2s
  }
}
```

##### 5. **Migration Base de Données**
**Fichier**: `backend/rag/migrations/0006_document_error_message_and_more.py`

**Opérations**:
```python
operations = [
    migrations.AddField(
        model_name='document',
        name='error_message',
        field=models.TextField(blank=True, null=True),
    ),
    migrations.AddField(
        model_name='document',
        name='processing_completed_at',
        field=models.DateTimeField(blank=True, null=True),
    ),
    migrations.AddField(
        model_name='document',
        name='processing_started_at',
        field=models.DateTimeField(blank=True, null=True),
    ),
    migrations.AddField(
        model_name='document',
        name='status',
        field=models.CharField(
            choices=[...],
            default='UPLOADED',
            max_length=20
        ),
    ),
]
```

**Appliquée avec**: `python manage.py migrate`

#### ✅ Tests Unitaires

**Fichier**: `backend/rag/tests/test_ingestion.py`

**8 tests implémentés**:

1. **`test_successful_ingestion`**: Vérifie que l'ingestion réussie met status=INDEXED
2. **`test_ingestion_failure`**: Vérifie que les exceptions sont capturées (status=FAILED)
3. **`test_ingest_nonexistent_document`**: Vérifie rejet des IDs invalides
4. **`test_upload_returns_202`**: Vérifie réponse HTTP correcte (202 Accepted)
5. **`test_upload_no_file`**: Vérifie validation (erreur 400 si pas de fichier)
6. **`test_upload_non_pdf`**: Vérifie validation (erreur 400 si pas un PDF)
7. **`test_get_document_status`**: Vérifie format de réponse du status endpoint
8. **`test_get_document_status_nonexistent`**: Vérifie gestion 404 pour IDs invalides

**Résultats**: ✅ 8/8 PASSED (0.145s)

**Commande**: `python manage.py test rag.tests.test_ingestion --no-input`

#### 📚 Documentation

##### README.md
**Ajouts**:
- Section "Asynchronous document processing" dans Features
- Documentation complète de l'API avec exemples curl
- Workflow de polling expliqué
- Exemples de réponses JSON

##### ARCHITECTURE.md
- Référence comme documentation de base pour comprendre le système

#### 🧪 Smoke Tests Validés

```bash
# 1. Sessions endpoint
curl http://localhost:8000/api/sessions/
✓ Retourne liste des sessions

# 2. Liste PDFs avec status
curl http://localhost:8000/api/pdfs/?session=yahia
✓ Retourne documents avec champ "status"

# 3. Upload asynchrone
curl -X POST http://localhost:8000/api/upload/ \
  -F "file=@paper.pdf" \
  -F "session=yahia"
✓ Retourne 202 Accepted avec document_id

# 4. Status polling
curl http://localhost:8000/api/documents/1/status/
✓ Retourne status détaillé avec processing_time_seconds

# 5. Vérification transition d'état
# Après 2 secondes: status passe de UPLOADED → INDEXED
✓ Processing time mesuré: 1.55 secondes
```

---

## 📊 Métriques D1

| Métrique | Valeur |
|----------|--------|
| Lignes de code ajoutées | 1,232 |
| Fichiers modifiés | 10 |
| Tests créés | 8 |
| Taux de réussite tests | 100% |
| Temps de traitement mesuré | 1.55s |
| Temps réponse upload | < 100ms (vs 30-60s avant) |

---

## 🎯 Impact Business

### Avant D1 ❌
- Upload bloquant 30-60 secondes
- Timeout frontend si PDF volumineux
- Pas de feedback pendant le traitement
- Impossible de savoir si l'indexation a échoué
- Un échec bloque toute l'application

### Après D1 ✅
- Upload instantané (< 100ms)
- Feedback temps réel avec polling
- Traçabilité complète (timestamps, durée, erreurs)
- Ingestions parallèles possibles
- Échecs isolés et "retryables"
- Ready pour intégration arXiv/PubMed (D2/D3)

---

## 🔗 Git

**Branch**: `feature/unified-ingestion`
**Commit**: `cab1842` - "feat(D1): Unified asynchronous ingestion pipeline"
**Push**: ✅ Poussé sur GitHub
**PR**: https://github.com/yzriga/PFE_AI/pull/new/feature/unified-ingestion

---

## 🚀 Prochaines Étapes

### En Attente
- [ ] Merger feature/unified-ingestion → main
- [ ] Démarrer D2: arXiv Connector

### D2 Prévu (arXiv Connector)
**Scope**:
- Service `ArxivService` (search + download)
- Modèle `PaperSource` (arXiv ID, DOI, metadata)
- Endpoints: `GET /api/arxiv/search`, `POST /api/arxiv/import`
- Tests avec mocks arXiv API
- Frontend: Composant recherche arXiv

**Estimation**: 3-4 heures

---

## 📝 Notes Techniques

### Choix d'Architecture

**Threading vs Celery**:
- ✅ Threading choisi pour D1 (simplicité, pas de dépendances)
- ⚠️ Celery recommandé pour production (D6: Monitoring)
- Raison: Threading suffit pour MVP, Celery ajouté plus tard

**Status Fields vs État Machine**:
- ✅ CharField avec choices (simple, queryable)
- Alternative considérée: django-fsm (overkill pour 4 états)

**Polling vs WebSocket**:
- ✅ Polling REST (compatible avec infrastructure actuelle)
- WebSocket envisagé pour D7 (frontend redesign)

### Lessons Learned

1. **Tests d'abord**: Les tests mock ont révélé un bug de threading avant production
2. **Logging essentiel**: Chaque étape loggée = debugging 10x plus rapide
3. **Migration testée**: Toujours tester migrate sur copie DB avant production
4. **Documentation synchronisée**: README mis à jour AVANT le push (pas après)

---

*Dernière mise à jour: 8 février 2026 - D1 complété*
