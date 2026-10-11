#!/usr/bin/env python3
"""
Talent Engine - mini-moteur de qualification de candidatures (SKULLVI / HCP).

Pipeline :
    reception (CSV ou saisie) -> validation -> dedoublonnage -> scoring (/100)
    -> classement -> priorite (A / B / C)

Aucune dependance externe : Python 3.8+ uniquement.

Usage :
    python talent_engine.py candidatures_exemple.csv -o classement.csv
    python talent_engine.py candidatures_exemple.csv --top 5
    python talent_engine.py nouvelles.csv --interactive   # ajoute un candidat au CSV
"""
import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------
# 1. Configuration du scoring (tout est ici : facile a ajuster et a expliquer)
# --------------------------------------------------------------------------
POIDS = {
    "competences": 35,    # largeur des competences techniques
    "projets": 25,        # preuves concretes : projets + liens verifiables
    "experience": 15,     # annees de pratique (plafonnees)
    "motivation": 15,     # qualite de la lettre / motivation
    "disponibilite": 10,  # disponibilite pour le demarrage du 2 novembre
}
assert sum(POIDS.values()) == 100

SEUIL_A = 70  # a examiner en priorite
SEUIL_B = 50  # a examiner ensuite

COMPETENCES_CIBLES = {
    "python", "javascript", "typescript", "sql", "html", "css", "git",
    "react", "node", "java", "php", "django", "flask", "docker", "linux",
    "api", "mongodb", "postgresql", "mysql", "c", "c++", "c#", "flutter",
    "tests", "figma", "data", "ia",
}
ALIAS = {
    "js": "javascript", "ts": "typescript", "node.js": "node", "nodejs": "node",
    "reactjs": "react", "react.js": "react", "postgres": "postgresql",
    "html5": "html", "css3": "css", "github": "git", "gitlab": "git",
    "rest": "api", "rest api": "api", "machine learning": "ia", "ml": "ia",
    "pandas": "data", "unit tests": "tests", "tests unitaires": "tests",
    "pytest": "tests",
}
MOTS_MOTIVATION = [
    "apprendre", "contribuer", "projet", "equipe", "équipe", "evoluer",
    "évoluer", "curieux", "curiosite", "curiosité", "problème", "probleme",
    "créer", "creer", "construire", "partager",
]
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


# --------------------------------------------------------------------------
# 2. Modele de donnees
# --------------------------------------------------------------------------
@dataclass
class Candidat:
    nom: str
    email: str
    competences: List[str]
    annees_experience: float
    nb_projets: int
    lien_portfolio: str
    motivation: str
    disponibilite: str  # "oui" | "partiel" | "non"
    # Resultats (remplis par le moteur)
    score: float = 0.0
    detail: dict = field(default_factory=dict)
    statut: str = "en attente"
    priorite: str = ""
    raisons: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# 3. Lecture / nettoyage des donnees (on anticipe les entrees sales)
# --------------------------------------------------------------------------
def _nombre(valeur, defaut=0.0) -> float:
    """Convertit '2', '2,5', ' 3 ans ' en float ; defaut si illisible. Jamais negatif."""
    if valeur is None:
        return defaut
    m = re.search(r"\d+(?:[.,]\d+)?", str(valeur))
    if not m:
        return defaut
    return max(0.0, float(m.group().replace(",", ".")))


def normaliser_competences(brut: str) -> List[str]:
    """'Python; JS, SQL' -> ['python', 'javascript', 'sql'] (sans doublons)."""
    resultat = []
    for part in re.split(r"[;,/|\n]", brut or ""):
        c = part.strip().lower()
        c = ALIAS.get(c, c)
        if c and c not in resultat:
            resultat.append(c)
    return resultat


def normaliser_disponibilite(brut: str) -> str:
    b = (brut or "").strip().lower()
    if b in {"oui", "yes", "o", "y", "disponible", "totale"}:
        return "oui"
    if b in {"partiel", "partielle", "partial", "mi-temps"}:
        return "partiel"
    return "non"


def ligne_vers_candidat(ligne: dict) -> Candidat:
    return Candidat(
        nom=(ligne.get("nom") or "").strip(),
        email=(ligne.get("email") or "").strip().lower(),
        competences=normaliser_competences(ligne.get("competences")),
        annees_experience=_nombre(ligne.get("annees_experience")),
        nb_projets=int(_nombre(ligne.get("nb_projets"))),
        lien_portfolio=(ligne.get("lien_portfolio") or "").strip(),
        motivation=(ligne.get("motivation") or "").strip(),
        disponibilite=normaliser_disponibilite(ligne.get("disponibilite")),
    )


def lire_csv(chemin: str) -> List[Candidat]:
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        return [ligne_vers_candidat(l) for l in csv.DictReader(f)]


# --------------------------------------------------------------------------
# 4. Validation : rejette ce qu'on ne peut pas contacter / identifier
# --------------------------------------------------------------------------
def valider(c: Candidat) -> Tuple[bool, Optional[str]]:
    if not c.nom:
        return False, "nom manquant"
    if not EMAIL_RE.match(c.email):
        return False, "email invalide ou manquant"
    return True, None


def dedoublonner(candidats: List[Candidat]) -> Tuple[List[Candidat], List[Candidat]]:
    """Un email = une candidature. On garde la derniere (la plus recente du fichier)."""
    vus = {}
    doublons = []
    for c in candidats:
        if c.email in vus:
            vus[c.email].statut = "doublon ignore"
            doublons.append(vus[c.email])
        vus[c.email] = c
    return list(vus.values()), doublons


# --------------------------------------------------------------------------
# 5. Scoring : chaque critere est borne pour eviter qu'un seul domine
# --------------------------------------------------------------------------
def score_competences(c: Candidat) -> float:
    reconnues = [x for x in c.competences if x in COMPETENCES_CIBLES]
    return min(len(reconnues), 7) / 7 * POIDS["competences"]  # plafond : 7 competences


def score_projets(c: Candidat) -> float:
    pts_nb = min(c.nb_projets, 4) / 4 * 15  # plafond : 4 projets
    lien = c.lien_portfolio.lower()
    pts_lien = 0.0
    if lien.startswith(("http://", "https://")) or "github.com" in lien:
        pts_lien = 10  # un lien verifiable vaut plus qu'une declaration
    return pts_nb + pts_lien


def score_experience(c: Candidat) -> float:
    return min(c.annees_experience, 3) / 3 * POIDS["experience"]  # plafond : 3 ans


def score_motivation(c: Candidat) -> float:
    texte = c.motivation.lower()
    n = len(texte)
    pts_longueur = 8 if n >= 200 else 5 if n >= 80 else 2 if n >= 20 else 0
    mots = sum(1 for m in MOTS_MOTIVATION if m in texte)
    pts_mots = min(mots, 4) / 4 * 7
    return pts_longueur + pts_mots


def score_disponibilite(c: Candidat) -> float:
    return {"oui": 10, "partiel": 5, "non": 0}[c.disponibilite]


CRITERES = {
    "competences": score_competences,
    "projets": score_projets,
    "experience": score_experience,
    "motivation": score_motivation,
    "disponibilite": score_disponibilite,
}


def noter(c: Candidat) -> Candidat:
    c.detail = {nom: round(f(c), 1) for nom, f in CRITERES.items()}
    c.score = round(sum(c.detail.values()), 1)
    # Raisons lisibles : le recruteur comprend pourquoi
    if c.detail["competences"] >= 25:
        c.raisons.append("bon socle technique")
    if c.detail["projets"] >= 20:
        c.raisons.append("projets concrets et verifiables")
    if c.lien_portfolio == "":
        c.raisons.append("aucun lien portfolio/GitHub")
    if c.detail["motivation"] < 7:
        c.raisons.append("motivation peu developpee")
    if c.disponibilite == "non":
        c.raisons.append("non disponible au demarrage")
    c.priorite = "A" if c.score >= SEUIL_A else "B" if c.score >= SEUIL_B else "C"
    c.statut = "qualifie"
    return c


# --------------------------------------------------------------------------
# 6. Pipeline complet
# --------------------------------------------------------------------------
def traiter(candidats: List[Candidat]):
    """Retourne (classes, rejetes). Classes = tries par score decroissant."""
    rejetes = []
    valides = []
    for c in candidats:
        ok, motif = valider(c)
        if ok:
            valides.append(c)
        else:
            c.statut = f"rejete : {motif}"
            rejetes.append(c)
    uniques, doublons = dedoublonner(valides)
    rejetes.extend(doublons)
    classes = [noter(c) for c in uniques]
    # Tri : score desc, puis plus de projets, puis nom (ordre stable et deterministe)
    classes.sort(key=lambda c: (-c.score, -c.nb_projets, c.nom.lower()))
    return classes, rejetes


# --------------------------------------------------------------------------
# 7. Sorties
# --------------------------------------------------------------------------
def afficher(classes: List[Candidat], rejetes: List[Candidat], top: Optional[int] = None):
    print(f"\n{'#':>2}  {'Prio':<4} {'Score':>5}  {'Nom':<24} Raisons")
    print("-" * 78)
    for i, c in enumerate(classes[:top] if top else classes, 1):
        print(f"{i:>2}  {c.priorite:<4} {c.score:>5}  {c.nom:<24} {', '.join(c.raisons)}")
    nb_a = sum(1 for c in classes if c.priorite == "A")
    print(f"\n{len(classes)} qualifies ({nb_a} a examiner en priorite), {len(rejetes)} ecartes.")
    for c in rejetes:
        print(f"  - ecarte : {c.nom or '(sans nom)'} <{c.email}> -> {c.statut}")


def exporter_csv(classes: List[Candidat], chemin: str):
    cols = ["rang", "priorite", "score", "nom", "email"] + list(POIDS) + ["raisons"]
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, c in enumerate(classes, 1):
            w.writerow([i, c.priorite, c.score, c.nom, c.email]
                       + [c.detail[k] for k in POIDS] + ["; ".join(c.raisons)])


def saisie_interactive(chemin: str):
    """Reception d'une candidature au clavier, ajoutee au CSV."""
    champs = ["nom", "email", "competences", "annees_experience", "nb_projets",
              "lien_portfolio", "motivation", "disponibilite"]
    aide = {"competences": " (separees par ;)", "disponibilite": " (oui/partiel/non)"}
    ligne = {k: input(f"{k}{aide.get(k, '')} : ") for k in champs}
    ok, motif = valider(ligne_vers_candidat(ligne))
    if not ok:
        print(f"Candidature refusee : {motif}")
        return
    try:
        existe = open(chemin, encoding="utf-8").read(1) != ""
    except FileNotFoundError:
        existe = False
    with open(chemin, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        if not existe:
            w.writeheader()
        w.writerow(ligne)
    print("Candidature enregistree.")


def main(argv=None):
    p = argparse.ArgumentParser(description="Talent Engine : qualification et classement")
    p.add_argument("fichier", help="CSV des candidatures")
    p.add_argument("-o", "--output", help="exporte le classement en CSV")
    p.add_argument("--top", type=int, help="n'affiche que les N premiers")
    p.add_argument("--interactive", action="store_true", help="ajoute une candidature au fichier")
    a = p.parse_args(argv)

    if a.interactive:
        saisie_interactive(a.fichier)
        return 0
    try:
        candidats = lire_csv(a.fichier)
    except FileNotFoundError:
        print(f"Fichier introuvable : {a.fichier}", file=sys.stderr)
        return 1
    classes, rejetes = traiter(candidats)
    afficher(classes, rejetes, a.top)
    if a.output:
        exporter_csv(classes, a.output)
        print(f"Classement exporte : {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
