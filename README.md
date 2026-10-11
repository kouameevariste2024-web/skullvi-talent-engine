# Talent Engine — Mini-Challenge SKULLVI / HCP

Première solution fonctionnelle pour **recevoir → collecter → qualifier → scorer → classer → prioriser** les candidatures.

Python 3.8+. Le moteur de scoring et le site fonctionnent **sans aucune dépendance** ; seule la lecture des CV au format PDF utilise `pypdf` (`pip install -r requirements.txt`, ou `apt install python3-pypdf` sur Ubuntu). Sans elle, le formulaire reste utilisable : le pré-remplissage est simplement indisponible pour les PDF (les DOCX restent lus).

## Lancer

```bash
python3 talent_engine.py candidatures_exemple.csv -o classement.csv   # classement + export
python3 talent_engine.py candidatures_exemple.csv --top 5             # les 5 premiers
python3 talent_engine.py candidatures_exemple.csv --interactive       # ajoute un candidat (réception)
python3 -m unittest -v                                                # 28 tests
```

## Version en ligne

**https://skullvicv.evaristekouame.com**

| Page | Rôle |
|---|---|
| `/` | Formulaire de candidature. Le **CV est le premier champ** : une fois envoyé, il pré-remplit le reste du formulaire |
| `/scoring` | Grille d'évaluation expliquée publiquement (transparence) |
| `/admin` | Espace administrateur protégé par mot de passe : compteurs, fiches classées avec le détail du score par critère, dossier complet, CV téléchargeable, filtres A/B/C, recherche, export CSV |

Mise en production : Ubuntu 24.04, service `systemd` (utilisateur dédié sans droits), nginx en reverse proxy, HTTPS Let's Encrypt (`deploy.sh`).

Sécurité : espace admin désactivé si aucun mot de passe n'est défini, authentification comparée en temps constant, limitation des envois par adresse, champ piège anti-robots, échappement de tout contenu affiché, vérification des CV (extension, taille, signature du fichier), CV stockés sous un nom aléatoire et accessibles uniquement à l'administrateur, export CSV protégé contre l'injection de formules.

## Pré-remplissage depuis le CV (`cv_parser.py`)

Le CV (PDF ou DOCX) est lu côté serveur, **sans IA** : extraction du texte, puis règles simples et explicables (expressions régulières, liste de compétences, détection des sections « Expérience » et « Projets »).

| Champ | Méthode |
|---|---|
| Nom | première ligne du haut ressemblant à « Prénom NOM » (2 à 4 mots, hors titres comme « Développeur ») |
| Email | première adresse trouvée |
| Compétences | compétences de la liste cible (+ alias : JS → JavaScript), dans l'ordre d'apparition |
| Années d'expérience | mention explicite (« 3 ans d'expérience »), sinon union des périodes datées de la section Expérience (la formation n'est pas comptée) |
| Projets | nombre de puces de la section Projets |
| Lien | GitHub / GitLab en priorité, sinon premier lien hors réseaux sociaux |

Principes : tout est une **suggestion** que le candidat vérifie et corrige (un champ déjà modifié à la main n'est jamais écrasé) ; la motivation et la disponibilité ne sont **jamais** pré-remplies ; le CV analysé n'est **pas stocké** tant que le formulaire n'est pas envoyé.

Limites assumées : CV scannés (images) et anciens `.doc` non lus (message clair, saisie manuelle, CV quand même joint) ; les heuristiques peuvent se tromper sur des mises en page atypiques, d'où la vérification par le candidat.

## Le problème, structuré

| Étape | Ce que fait le code | Fonction |
|---|---|---|
| Réception | Lecture d'un CSV ou saisie au clavier | `lire_csv`, `saisie_interactive` |
| Collecte | 8 champs essentiels, nettoyés et normalisés | `ligne_vers_candidat` |
| Qualification | Rejet si nom ou email invalide ; 1 email = 1 candidature | `valider`, `dedoublonner` |
| Score | Note /100 sur 5 critères, détail conservé | `noter` |
| Classement | Tri par score, puis nb de projets, puis nom | `traiter` |
| Priorité | A (≥70) à examiner d'abord, B (≥50), C | `SEUIL_A`, `SEUIL_B` |

## Grille de scoring (100 points)

| Critère | Points | Logique | Pourquoi |
|---|---|---|---|
| Compétences | 35 | Nb de compétences reconnues, plafonné à 7 | Mesure la largeur du socle sans récompenser l'inflation |
| Projets | 25 | Jusqu'à 15 pts pour le nb de projets (plafond 4) + 10 pts si lien vérifiable | Une preuve (GitHub, portfolio) vaut plus qu'une déclaration |
| Expérience | 15 | Années de pratique, plafonnées à 3 ans | Le potentiel compte plus que l'ancienneté |
| Motivation | 15 | Longueur du texte (8 pts) + mots-clés d'état d'esprit (7 pts) | Valorise apprendre, contribuer, esprit d'équipe |
| Disponibilité | 10 | oui = 10, partiel = 5, non = 0 | Démarrage le 2 novembre 2026 |

Chaque critère est **plafonné** : aucun ne peut dominer seul. Chaque candidat reçoit aussi des **raisons lisibles** (« aucun lien portfolio/GitHub », « motivation peu développée »…) pour que le recruteur comprenne le score au lieu de le subir.

Tous les poids et seuils sont regroupés en haut de `talent_engine.py` : on peut ajuster la grille sans toucher à la logique.

## Erreurs anticipées

- Nombres sales (`"2,5 ans"`, `"abc"`, valeurs négatives) → convertis ou ramenés à 0
- Compétences hétérogènes (`JS`, `Node.js`, `github`) → normalisées par alias, doublons supprimés
- Email invalide / nom manquant → écartés **avec le motif affiché** (rien ne disparaît en silence)
- Doublons (casse différente de l'email) → on garde la candidature la plus récente
- Fichier introuvable → message clair, pas de crash
- Liste vide → pas d'erreur

## Tests (`test_talent_engine.py`)

Nettoyage des données, validation, score borné entre 0 et 100, poids = 100, effet du lien vérifiable, priorités, dédoublonnage, tri déterministe, liste vide, et un test de bout en bout sur `candidatures_exemple.csv`.

## Limites assumées et pistes d'évolution

- **Le score est une aide à la décision, pas une décision.** Il sert à trier la file d'examen ; un humain tranche. Un profil atypique à score faible reste consultable dans l'export.
- Le score de motivation est volontairement simple (longueur + mots-clés) : il peut être contourné. Une évolution serait de faire lire les textes par un humain pour les profils A/B seulement.
- Les compétences reconnues sont une liste fixe (`COMPETENCES_CIBLES`) à faire évoluer selon les besoins de SKULLVI.
- Évolutions possibles : formulaire web, base de données, vérification réelle des liens GitHub, vérification d'équité du scoring (éviter de pénaliser les parcours autodidactes).

## Utilisation de l'IA

J'ai utilisé un assistant IA pour accélérer l'écriture du code et des tests. **À compléter avec votre contribution personnelle** : choix de la grille, ajustements, relecture, ce que vous avez compris et modifié.
