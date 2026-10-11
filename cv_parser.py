"""
Lecture de CV et pre-remplissage du formulaire (Talent Engine).

Approche volontairement simple et explicable : extraction de texte (PDF / DOCX)
puis regles (regex + listes), sans IA. Tout est une SUGGESTION que le candidat
verifie et corrige avant d'envoyer.

    texte, erreur = extraire_texte("cv.pdf", octets)
    champs = analyser(texte)   # {'nom', 'email', 'competences', 'annees_experience', 'nb_projets', 'lien_portfolio'}
"""
import datetime
import html
import io
import re
import zipfile

import talent_engine as te

MAX_PAGES = 8                 # on ne lit que les premieres pages (limite le cout / les abus)
MAX_TEXTE = 60_000            # caracteres
MAX_XML = 5 * 1024 * 1024     # protection contre les DOCX "bombes"

# ----------------------------------------------------------------- extraction du texte
def _texte_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "Lecture des PDF indisponible sur ce serveur."
    try:
        lecteur = PdfReader(io.BytesIO(data))
        if lecteur.is_encrypted:
            return "", "Ce PDF est protégé par un mot de passe."
        pages = lecteur.pages[:MAX_PAGES]
        return "\n".join((p.extract_text() or "") for p in pages)[:MAX_TEXTE], ""
    except Exception:
        return "", "Impossible de lire ce PDF."


def _texte_docx(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_XML:
                return "", "Document trop volumineux pour la lecture automatique."
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:
        return "", "Impossible de lire ce document Word."
    xml = re.sub(r"</w:p>|<w:br\s*/>|<w:tab\s*/>", "\n", xml)
    texte = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return texte[:MAX_TEXTE], ""


def extraire_texte(nom_fichier, data):
    """-> (texte, message_erreur). Un texte vide + erreur = on ne pre-remplit rien."""
    nom = nom_fichier.lower()
    if nom.endswith(".pdf"):
        texte, err = _texte_pdf(data)
    elif nom.endswith(".docx"):
        texte, err = _texte_docx(data)
    elif nom.endswith(".doc"):
        return "", "Les anciens fichiers .doc ne sont pas lus automatiquement : remplissez le formulaire à la main (votre CV sera quand même joint)."
    else:
        return "", "Format non pris en charge."
    if not err and len(texte.strip()) < 30:
        err = "Aucun texte lisible (CV scanné ou image ?). Remplissez le formulaire à la main."
    return texte, err


# ----------------------------------------------------------------- analyse
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')\],;]+", re.I)
GIT_RE = re.compile(r"(?:https?://)?(?:www\.)?(?:github|gitlab)\.com/[\w.-]+(?:/[\w.-]+)?", re.I)
MOTS_NON_NOM = {
    "curriculum", "vitae", "cv", "resume", "résumé", "profil", "profile", "contact", "développeur",
    "developpeur", "developer", "ingénieur", "ingenieur", "engineer", "étudiant", "etudiant", "stagiaire",
    "full", "stack", "web", "software", "informatique", "data", "analyst", "analyste", "mobile", "backend",
    "frontend", "front", "back", "end", "junior", "senior", "freelance", "technicien", "de", "en", "et",
}
SECTIONS = {
    "exp": r"exp[ée]riences?(?:\s+professionnelles?)?|parcours\s+professionnel|work\s+experience|experience",
    "proj": r"projets?(?:\s+(?:personnels?|r[ée]alis[ée]s?|acad[ée]miques?))?|projects?|r[ée]alisations?",
    "autre": r"formations?|[ée]ducation|[ée]tudes|dipl[oô]mes?|comp[ée]tences?(?:\s+\w+)?|skills|langues?|languages?|loisirs|"
             r"centres?\s+d.int[ée]r[êe]ts?|certifications?|profil|r[ée]sum[ée]|objectifs?|contact|r[ée]f[ée]rences?|"
             r"informations?\s+personnelles?|[àa]\s+propos",
}
SECTION_RES = {k: re.compile(rf"^(?:{v})$", re.I) for k, v in SECTIONS.items()}

ANNEE = r"(?:19|20)\d{2}"
FIN = rf"(?:(?:\d{{1,2}}[/.]|[A-Za-zéèêûôî]{{3,10}}\.?\s+)?({ANNEE})|(pr[ée]sent|aujourd.hui|actuel\w*|present|now|en\s+cours))"
PLAGE_RE = re.compile(rf"({ANNEE})\s*(?:-|–|—|/|à|au|to)\s*{FIN}", re.I)
EXPL_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:ans?|years?)\s*(?:d['’]\s*|of\s+)?exp[ée]rience", re.I)
# une puce = un symbole non alphanumerique en debut de ligne (les PDF sortent souvent des caracteres
# etranges : \x7f, \uf0b7...) ou une numerotation "1." / "2)"
PUCE_RE = re.compile(r"^\s*(?:[^\w\s(\[\"'«“]|\d{1,2}[.)])\s*\S")

AFFICHAGE = {"ia": "IA", "sql": "SQL", "html": "HTML", "css": "CSS", "api": "API", "php": "PHP", "mysql": "MySQL",
             "postgresql": "PostgreSQL", "mongodb": "MongoDB", "javascript": "JavaScript", "typescript": "TypeScript",
             "node": "Node.js", "c++": "C++", "c#": "C#", "git": "Git", "linux": "Linux", "docker": "Docker",
             "tests": "Tests", "data": "Data", "figma": "Figma", "flutter": "Flutter"}


def _motifs_competences():
    """[(competence canonique, regex)] : noms cibles + alias (js -> javascript...). 'c' seul est ignore (trop bruite)."""
    noms = {c: c for c in te.COMPETENCES_CIBLES if c != "c"}
    noms.update({a: c for a, c in te.ALIAS.items()})
    out = []
    for texte, canon in noms.items():
        motif = rf"(?<![A-Za-z0-9+#]){re.escape(texte)}(?![A-Za-z0-9+#])"
        # "IA" en majuscules uniquement (evite les faux positifs) ; le reste insensible a la casse
        out.append((canon, re.compile(motif, 0 if texte == "ia" else re.I), texte == "ia"))
    return out


_MOTIFS = _motifs_competences()


def trouver_competences(texte):
    """Competences reconnues, dans l'ordre ou elles apparaissent dans le CV."""
    positions = {}
    for canon, rx, _ in _MOTIFS:
        m = rx.search(texte)
        if m:
            positions[canon] = min(positions.get(canon, 10**9), m.start())
    return [AFFICHAGE.get(c, c.capitalize()) for c in sorted(positions, key=positions.get)]


def trouver_email(texte):
    m = EMAIL_RE.search(texte)
    return m.group().lower() if m else ""


def trouver_nom(texte):
    """Premiere ligne du haut qui ressemble a 'Prenom NOM' (2 a 4 mots alphabetiques)."""
    for ligne in [l.strip() for l in texte.splitlines() if l.strip()][:8]:
        if "@" in ligne or any(ch.isdigit() for ch in ligne) or len(ligne) > 40:
            continue
        mots = ligne.replace("’", "'").split()
        if not 2 <= len(mots) <= 4:
            continue
        if not all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", m) for m in mots):
            continue
        if any(m.lower() in MOTS_NON_NOM for m in mots):
            continue
        return ligne.title() if ligne.isupper() else ligne
    return ""


def trouver_lien(texte):
    m = GIT_RE.search(texte)
    if m:
        lien = m.group().rstrip(".,;)")
    else:
        lien = ""
        for u in URL_RE.findall(texte):
            if not re.search(r"linkedin|facebook|instagram|twitter|wa\.me|whatsapp", u, re.I):
                lien = u.rstrip(".,;)")
                break
    if lien and not lien.lower().startswith("http"):
        lien = "https://" + lien
    return lien


def decouper(texte):
    """Repere les titres de sections -> {'exp': [lignes], 'proj': [lignes]}."""
    sections, courant = {"exp": [], "proj": []}, None
    for brut in texte.splitlines():
        titre = re.sub(r"^[\s•\-–—_#*]+|[\s:•\-–—_#*]+$", "", brut)
        genre = None
        if 3 <= len(titre) <= 45:
            genre = next((k for k, rx in SECTION_RES.items() if rx.match(titre)), None)
        if genre:
            courant = genre if genre in sections else None   # un titre "autre" ferme la section en cours
        elif courant:
            sections[courant].append(brut)
    return sections


def estimer_experience(texte, sections):
    """Annees d'experience : mention explicite, sinon union des periodes datees de la section Experience."""
    explicites = [int(n) for n in EXPL_RE.findall(texte)]
    if explicites:
        return float(min(max(explicites), 30))
    bloc = "\n".join(sections.get("exp", []))
    if not bloc.strip():
        return 0.0
    annee_courante = datetime.date.today().year
    periodes = []
    for m in PLAGE_RE.finditer(bloc):
        debut = int(m.group(1))
        fin = int(m.group(2)) if m.group(2) else annee_courante
        if fin < debut or debut > annee_courante:
            continue
        periodes.append((debut, max(fin, debut)))
    if not periodes:
        return 0.0
    periodes.sort()
    fusion = [list(periodes[0])]
    for d, f in periodes[1:]:
        if d <= fusion[-1][1]:
            fusion[-1][1] = max(fusion[-1][1], f)
        else:
            fusion.append([d, f])
    total = sum((f - d) or 0.5 for d, f in fusion)   # une annee isolee compte pour 6 mois
    return min(round(total * 2) / 2, 15.0)


def compter_projets(sections):
    lignes = sections.get("proj", [])
    if not any(l.strip() for l in lignes):
        return 0
    puces = sum(1 for l in lignes if PUCE_RE.match(l))
    if puces:
        return min(puces, 10)
    paragraphes = [p for p in re.split(r"\n\s*\n", "\n".join(lignes)) if p.strip()]
    return min(max(len(paragraphes), 1), 10)


def analyser(texte):
    sections = decouper(texte)
    return {
        "nom": trouver_nom(texte),
        "email": trouver_email(texte),
        "competences": "; ".join(trouver_competences(texte)),
        "annees_experience": estimer_experience(texte, sections),
        "nb_projets": compter_projets(sections),
        "lien_portfolio": trouver_lien(texte),
    }
