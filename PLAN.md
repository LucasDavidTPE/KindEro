# KindEro — plan de développement

> Document de pilotage. Il sert de mémoire au projet : l'orchestrateur (Claude)
> et chaque sous-agent le lisent avant d'agir, et on le met à jour à chaque étape.

## Objectif

Relier **Zotero** et une **Kindle**, sans jailbreak, avec une appli libre (GPL-3.0) :

1. **Aller** — choisir des articles ou une collection Zotero et les envoyer sur la
   Kindle par « Send to Kindle » (e-mail), avec un nom de fichier et des
   métadonnées propres (`Auteur - Titre.pdf`).
2. **Retour** — lire `My Clippings.txt` (Kindle branchée en USB) et ajouter les
   surlignages et notes comme **note enfant** sur le bon article Zotero, sans
   créer de doublon quand on relance.

Contraintes : rien à installer sur la liseuse ; uniquement l'API Web Zotero v3,
le SMTP, et le fichier `My Clippings.txt`. Python ≥ 3.10, Windows/macOS/Linux.

## Architecture

```
kindero/
  models.py      # dataclasses partagées (contrat entre modules) — FIGÉ
  config.py      # lecture/écriture config TOML + secrets par variables d'env
  zotero.py      # client API Web Zotero v3 (requests)
  kindle.py      # préparation du fichier + envoi SMTP vers l'adresse Kindle
  clippings.py   # parseur My Clippings.txt (EN + FR + DE + ES), dédoublonnage
  sync.py        # rapprochement clippings ↔ items Zotero, rendu HTML de la note
  devices.py     # détection de la Kindle montée (Windows/macOS/Linux)
  cli.py         # commande `kindero` (argparse)
tests/           # pytest, aucun accès réseau (HTTP et SMTP simulés)
```

Dépendances d'exécution : `requests`, `pypdf`, `tomli` (Python < 3.11 seulement).
Dépendances de test : `pytest`.

### Contrats (signatures figées)

Les modules ne se parlent qu'à travers ces signatures. Un sous-agent qui a besoin
d'un changement le signale à l'orchestrateur au lieu de le faire lui-même.

```python
# config.py
def config_path() -> Path
def load_config(path: Path | None = None) -> Config        # lève ConfigError
def save_config(cfg: Config, path: Path | None = None) -> Path

# zotero.py
class ZoteroClient:
    def __init__(self, library_id: str, api_key: str, library_type: str = "user",
                 session: requests.Session | None = None,
                 base_url: str = "https://api.zotero.org")
    def collections(self) -> list[Collection]
    def items(self, collection_key: str | None = None, query: str | None = None,
              limit: int | None = None) -> list[Item]           # items de 1er niveau
    def item(self, key: str) -> Item
    def attachments(self, item_key: str) -> list[Attachment]
    def download(self, attachment: Attachment) -> bytes
    def notes(self, item_key: str) -> list[Note]
    def create_note(self, parent_key: str, html: str, tags: list[str]) -> str  # clé
    def update_note(self, note: Note, html: str) -> None

# kindle.py
SUPPORTED_EXTENSIONS: frozenset[str]
MAX_EMAIL_BYTES: int
def kindle_filename(item: Item, attachment: Attachment) -> str
def prepare_document(item: Item, attachment: Attachment, data: bytes) -> tuple[str, bytes]
def send_to_kindle(docs: list[tuple[str, bytes]], cfg: Config,
                   smtp_factory=smtplib.SMTP) -> None           # lève SendError

# clippings.py
def parse_clippings(text: str) -> list[Clipping]
def read_clippings_file(path: Path) -> list[Clipping]          # gère le BOM UTF-8
def group_by_book(clips: list[Clipping]) -> dict[tuple[str, str], list[Clipping]]
def dedupe(clips: list[Clipping]) -> list[Clipping]            # surlignages étendus

# sync.py
def match_book(title: str, author: str, items: list[Item],
               threshold: float = 0.85) -> Item | None
def render_note(title: str, clips: list[Clipping]) -> str      # HTML, contient MARKER
def sync_clippings(clips: list[Clipping], client: ZoteroClient,
                   dry_run: bool = False) -> list[SyncResult]

# devices.py
def find_kindle_clippings() -> Path | None
```

Les dataclasses (`Config`, `Collection`, `Item`, `Attachment`, `Note`,
`Clipping`, `SyncResult`) et les exceptions sont dans `kindero/models.py`.

### Choix techniques

- **Idempotence du retour** : chaque note créée porte le tag `kindero` et un
  commentaire HTML `<!-- kindero:book=<sha1 titre+auteur> -->`. Au relancement,
  on retrouve la note par ce marqueur et on la **met à jour** (PATCH avec
  `If-Unmodified-Since-Version`) au lieu d'en créer une autre.
- **Rapprochement** : titre normalisé (minuscules, sans accents ni ponctuation,
  sans le suffixe ` (Auteur)` et sans l'extension de fichier), puis
  `difflib.SequenceMatcher` ; bonus si le nom de l'auteur correspond. Sous le
  seuil → l'article est listé « non trouvé », jamais rattaché au hasard.
- **Envoi** : SMTP STARTTLS (587) ou SSL (465). Le mot de passe vient de la
  variable d'environnement `KINDERO_SMTP_PASSWORD` ou de la config. Un e-mail
  ne dépasse pas 50 Mo ; au-delà, l'envoi est réparti sur plusieurs e-mails.
  L'adresse d'expédition doit être approuvée sur le compte Amazon (rappelé
  dans le README et dans les messages d'erreur).
- **PDF** : on réécrit le titre et l'auteur dans les métadonnées avec `pypdf`
  (c'est ce qu'affiche la Kindle) ; en cas d'échec, on envoie le fichier tel quel.

## Répartition des tâches (orchestration)

| # | Tâche | Fichiers | Agent / modèle | État |
|---|-------|----------|----------------|------|
| 0 | Plan, contrats, squelette, `models.py`, `pyproject.toml` | PLAN.md, kindero/models.py | orchestrateur | ✅ |
| 1 | Client API Zotero + tests | zotero.py, tests/test_zotero.py | sous-agent sonnet | ⏳ |
| 2 | Parseur My Clippings + détection Kindle + tests | clippings.py, devices.py, tests/test_clippings.py | sous-agent sonnet | ⏳ |
| 3 | Préparation et envoi Kindle + config + tests | kindle.py, config.py, tests/test_kindle.py, tests/test_config.py | sous-agent sonnet | ⏳ |
| 4 | Synchro clippings → notes + tests | sync.py, tests/test_sync.py | sous-agent opus (logique la plus délicate) | ⏳ |
| 5 | CLI | cli.py, tests/test_cli.py | orchestrateur, après 1–4 | ⏳ |
| 6 | README (FR + EN), LICENSE GPL-3.0, CONTRIBUTING | README.md, LICENSE | sous-agent haiku | ⏳ |
| 7 | Intégration, tests complets, relecture, commit, push | — | orchestrateur | ⏳ |

Règles pour les sous-agents : ne toucher qu'à ses fichiers, ne pas modifier
`models.py` ni les signatures, aucun appel réseau dans les tests, **ne pas faire
de commit** (l'orchestrateur commit après relecture).

## Suite (après la v0.1)

- Interface graphique légère (Tkinter ou page web locale) pour cocher les articles.
- Envoi direct d'EPUB avec couverture générée.
- Importer les surlignages comme vraies annotations Zotero (position dans le
  PDF) quand on peut retrouver la page — plus difficile, l'emplacement Kindle
  ne correspond pas à une position PDF.
- Lecture de la bibliothèque Zotero locale (`zotero.sqlite`) pour les
  utilisateurs sans synchronisation des fichiers.
- Paquet PyPI et exécutable Windows (PyInstaller) publiés via GitHub Actions.

## Journal

- 2026-10-28 — Plan rédigé, contrats figés, lancement des sous-agents 1 à 4 et 6.
