# KindEro

**KindEro relie Zotero et une Kindle, sans jailbreak.** Logiciel libre, sous licence GPL-3.0-or-later.

---

## Français

### Ce que fait KindEro

1. **Envoyer vers la Kindle** : KindEro envoie les articles ou une collection Zotero sur la Kindle via « Send to Kindle » (envoi par e-mail). Les fichiers reçoivent un nom propre (`Auteur - Titre.pdf`) et les métadonnées PDF (titre, auteur) sont corrigées pour que la Kindle les affiche correctement.
2. **Rapatrier les surlignages** : KindEro lit le fichier `My Clippings.txt` de la Kindle (branchée en USB) et ajoute les surlignages et notes comme **note enfant** sur l'article Zotero correspondant. Relancer la commande ne crée pas de doublon : la note est mise à jour.

### Pourquoi pas de jailbreak ?

KindEro n'installe rien sur la liseuse. Il n'utilise que trois choses : l'envoi par e-mail « Send to Kindle » d'Amazon, le fichier `My Clippings.txt` que la Kindle produit elle-même, et l'API Web de Zotero.

Si vous acceptez un appareil modifié, d'autres solutions existent :

- **KOReader** avec le greffon **zotero.koplugin** pour les liseuses jailbreakées ;
- le greffon Zotero **Kanzi**, qui ne traite que les surlignages (pas l'envoi des fichiers).

### Prérequis

- **Python 3.10** ou plus récent.
- Un **compte Zotero** dont les fichiers sont synchronisés avec le stockage Zotero. Les fichiers liés (« linked files ») ne peuvent pas être téléchargés via l'API.
- Une **clé d'API Zotero**, à créer sur <https://www.zotero.org/settings/keys> avec un accès **en lecture** à la bibliothèque et un accès **en écriture** (pour créer les notes).
- Votre **identifiant de bibliothèque** (« Your userID for use in API calls »), affiché sur la même page.
- Votre **adresse e-mail Kindle** : sur Amazon, allez dans *Gérer vos contenus et vos appareils* → *Préférences* → *Paramètres des documents personnels*.
- Ajoutez l'adresse e-mail qui enverra les fichiers à la **liste des e-mails approuvés pour les documents personnels** (même page Amazon). Sans cela, Amazon refuse l'envoi.
- Les **identifiants SMTP** de cette adresse d'envoi. Avec Gmail ou Outlook, il faut un **mot de passe d'application**.

### Installation

Installation directe depuis GitHub :

```bash
pip install git+https://github.com/LucasDavidTPE/KindEro
```

Pour développer :

```bash
git clone https://github.com/LucasDavidTPE/KindEro
cd KindEro
pip install -e ".[dev]"
```

### Utilisation

```bash
# Configuration interactive : enregistre la config dans le dossier de configuration utilisateur
kindero init

# Lister les collections Zotero
kindero collections

# Lister les articles et leurs clés
kindero items [--collection NOM] [--search TEXTE]

# Envoyer des pièces jointes d'articles à la Kindle
kindero send CLE_ARTICLE [CLE_ARTICLE ...]
kindero send --collection NOM

# Importer les surlignages depuis My Clippings.txt
kindero import-clippings [CHEMIN]
```

Notes :

- `kindero init` demande le mot de passe SMTP. Vous pouvez aussi le fournir par la variable d'environnement `KINDERO_SMTP_PASSWORD`, sans l'enregistrer dans la configuration.
- `kindero send` accepte `--dry-run` pour prévisualiser l'envoi sans rien envoyer.
- `kindero import-clippings` accepte `--dry-run` pour prévisualiser l'import. Sans `CHEMIN`, KindEro cherche la Kindle branchée et son fichier `documents/My Clippings.txt`.

### Limites

- Les **annotations manuscrites** sur les PDF d'une Kindle Scribe ne figurent pas dans `My Clippings.txt`.
- Amazon limite les e-mails à **50 Mo** : KindEro répartit automatiquement l'envoi sur plusieurs e-mails si besoin.
- Les emplacements Kindle ne correspondent pas à des positions dans le PDF. Les surlignages sont donc ajoutés **sous forme de note**, et non comme annotations positionnées dans Zotero.
- Les documents personnels synchronisés par Whispersync n'apparaissent que dans le fichier `My Clippings.txt` de l'appareil sur lequel vous avez surligné.

### Confidentialité

Vos identifiants restent sur votre ordinateur. KindEro ne communique qu'avec **api.zotero.org** et avec **votre serveur SMTP**.

### Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md).

### Licence

KindEro est un logiciel libre distribué sous la **GNU General Public License version 3** (ou toute version ultérieure). Voir [LICENSE](LICENSE).

---

## English

### What KindEro does

KindEro connects Zotero and a Kindle without jailbreaking the device.

1. **Send to Kindle**: KindEro sends Zotero papers or a whole collection to your Kindle through Amazon's "Send to Kindle" e-mail service. Files get clean names (`Author - Title.pdf`), and the PDF title and author metadata are corrected so the Kindle displays them properly.
2. **Bring highlights back**: KindEro reads the Kindle's `My Clippings.txt` (Kindle connected over USB) and adds highlights and notes as a **child note** on the matching Zotero item. Running the import again does not create duplicates; the existing note is updated.

### Why no jailbreak?

KindEro installs nothing on the e-reader. It relies only on Amazon's Send-to-Kindle e-mail, the `My Clippings.txt` file the Kindle already writes, and the Zotero Web API.

If you are willing to modify your device, other options exist:

- **KOReader** with the **zotero.koplugin** plugin, for jailbroken e-readers;
- the Zotero plugin **Kanzi**, which handles highlights only (it does not send files).

### Requirements

- **Python 3.10** or newer.
- A **Zotero account** with files synced to Zotero storage. Linked files cannot be downloaded through the API.
- A **Zotero API key**, created at <https://www.zotero.org/settings/keys> with **read** access to your library and **write** access (needed to create notes).
- Your **library ID** ("Your userID for use in API calls"), shown on the same page.
- Your **Kindle e-mail address**: on Amazon, go to *Manage Your Content and Devices* → *Preferences* → *Personal Document Settings*.
- Add the sending e-mail address to the **Approved Personal Document E-mail List** on the same page. Amazon rejects documents from unapproved senders.
- **SMTP credentials** for that sending address. Gmail and Outlook require an **app password**.

### Installation

Install directly from GitHub:

```bash
pip install git+https://github.com/LucasDavidTPE/KindEro
```

For development:

```bash
git clone https://github.com/LucasDavidTPE/KindEro
cd KindEro
pip install -e ".[dev]"
```

### Usage

```bash
# Interactive setup; stores the config in the user config directory
kindero init

# List Zotero collections
kindero collections

# List items and their keys
kindero items [--collection NAME] [--search TEXT]

# Send item attachments to the Kindle
kindero send ITEM_KEY [ITEM_KEY ...]
kindero send --collection NAME

# Import highlights from My Clippings.txt
kindero import-clippings [PATH]
```

Notes:

- `kindero init` asks for the SMTP password. You can instead provide it through the `KINDERO_SMTP_PASSWORD` environment variable, so it is not saved in the config.
- `kindero send` accepts `--dry-run` to preview what would be sent without sending anything.
- `kindero import-clippings` accepts `--dry-run` to preview the import. Without `PATH`, KindEro looks for a connected Kindle and its `documents/My Clippings.txt` file.

### Limitations

- Handwritten annotations on PDFs in a Kindle Scribe are not included in `My Clippings.txt`.
- Amazon limits e-mails to **50 MB**; KindEro splits larger sends across several e-mails automatically.
- Kindle locations do not map to positions in the PDF, so highlights are added as a **note**, not as positioned annotations in Zotero.
- Personal documents synced via Whispersync appear only in the `My Clippings.txt` of the device where you highlighted them.

### Privacy

Your credentials stay on your computer. KindEro only communicates with **api.zotero.org** and **your SMTP server**.

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

### License

KindEro is free software, distributed under the **GNU General Public License version 3** (or, at your option, any later version). See [LICENSE](LICENSE).
