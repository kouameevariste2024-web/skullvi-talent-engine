#!/usr/bin/env python3
"""
Talent Engine - interface web (bibliotheque standard uniquement).

Pages publiques :  /  (formulaire)   /merci   /scoring (grille expliquee)
Espace admin    :  /admin  (+ /admin/export.csv)   -> protege par mot de passe

    ADMIN_PASSWORD=...  python3 web_app.py

Variables : PORT (8000), HOST (127.0.0.1), DATA_FILE (candidatures.csv), ADMIN_PASSWORD
Sans ADMIN_PASSWORD, l'espace admin est desactive (securise par defaut).
"""
import base64
import csv
import email
import email.policy
import hmac
import html
import io
import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv_parser
import talent_engine as te

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
DATA_FILE = os.environ.get("DATA_FILE", "candidatures.csv")
ADMIN_USER = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MAX_BODY = 20_000            # octets (formulaire sans fichier)
CV_MAX = 3 * 1024 * 1024     # 3 Mo par CV
MAX_UPLOAD = CV_MAX + 100_000
CV_DIR = os.environ.get("CV_DIR") or os.path.join(os.path.dirname(os.path.abspath(DATA_FILE)), "cv")
CV_NOM_RE = re.compile(r"^[a-f0-9]{32}\.(pdf|doc|docx)$")
CV_TYPES = {".pdf": "application/pdf", ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
RATE_MAX, RATE_WINDOW = 8, 600   # 8 envois / 10 min / IP
LOCK = threading.Lock()
ENVOIS = defaultdict(list)
PARSES = defaultdict(list)   # lectures de CV par IP
PARSE_MAX = 20               # 20 lectures / 10 min / IP
CHAMPS = ["nom", "email", "competences", "annees_experience", "nb_projets",
          "lien_portfolio", "motivation", "disponibilite"]
FIELDNAMES = CHAMPS + ["cv"]
LIBELLES = {"competences": "Compétences", "projets": "Projets & preuves",
            "experience": "Expérience", "motivation": "Motivation",
            "disponibilite": "Disponibilité"}
EXPLICATIONS = {
    "competences": "Nombre de compétences techniques reconnues (plafond : 7). Mesure la largeur du socle sans récompenser l'inflation de la liste.",
    "projets": "Jusqu'à 15 pts selon le nombre de projets réalisés (plafond : 4) + 10 pts si un lien vérifiable (GitHub, portfolio) est fourni. Une preuve vaut plus qu'une déclaration.",
    "experience": "Années de pratique, plafonnées à 3 ans : on cherche du potentiel, pas de l'ancienneté.",
    "motivation": "Longueur et richesse du texte (8 pts) + présence de mots liés à l'état d'esprit : apprendre, contribuer, équipe, curiosité… (7 pts).",
    "disponibilite": "Disponibilité pour le démarrage du 2 novembre 2026 : oui = 10, partiel = 5, non = 0.",
}

CSS = """
:root{--bg:#f4f5f9;--card:#fff;--ink:#14161f;--mut:#667085;--line:#e4e7ee;--brand:#4f46e5;--brand2:#7c3aed;
--a:#047857;--abg:#d1fae5;--b:#b45309;--bbg:#fef3c7;--c:#475467;--cbg:#eceff3;--err:#b42318;--errbg:#fee4e2}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);line-height:1.5}
header{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff;padding:2rem 1rem 3.5rem}
header .in,main{max-width:860px;margin:0 auto}
header h1{margin:0;font-size:1.8rem}header p{margin:.3rem 0 0;opacity:.9}
nav{margin-top:1rem;display:flex;gap:1rem;font-size:.9rem}nav a{color:#fff;opacity:.85}nav a:hover{opacity:1}
main{padding:0 1rem 3rem;margin-top:-2.2rem}
.panel{background:var(--card);border-radius:14px;padding:1.4rem;box-shadow:0 4px 18px rgba(20,22,31,.07);margin-bottom:1.2rem}
form{display:grid;gap:.9rem}label{display:grid;gap:.25rem;font-size:.88rem;font-weight:600}
label small{font-weight:400;color:var(--mut)}
input,textarea,select{padding:.65rem .75rem;border:1px solid var(--line);border-radius:9px;font:inherit;background:#fff}
input:focus,textarea:focus,select:focus{outline:2px solid var(--brand);border-color:transparent}
.row{display:grid;grid-template-columns:1fr 1fr;gap:.9rem}@media(max-width:600px){.row{grid-template-columns:1fr}}
button,.btn{padding:.8rem 1rem;background:var(--brand);color:#fff;border:0;border-radius:9px;font:inherit;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block;text-align:center}
button:hover,.btn:hover{background:#4338ca}.btn.sec{background:#fff;color:var(--brand);border:1px solid var(--line)}
.alert{padding:.8rem 1rem;border-radius:9px;margin-bottom:1rem}.alert.err{background:var(--errbg);color:var(--err)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:.7rem;margin-bottom:1.2rem}
.stat{background:var(--card);border-radius:12px;padding:.9rem;text-align:center;box-shadow:0 2px 10px rgba(20,22,31,.05)}
.stat b{font-size:1.6rem;display:block}.stat span{color:var(--mut);font-size:.8rem}
.tools{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin-bottom:1rem}
.tools form{display:flex;gap:.5rem;flex:1;min-width:200px}.tools input{flex:1}
.chip{padding:.35rem .8rem;border-radius:99px;background:#fff;border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:.85rem}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.card{background:var(--card);border-radius:14px;padding:1.1rem 1.2rem;margin-bottom:.9rem;box-shadow:0 2px 10px rgba(20,22,31,.05)}
.head{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}.head h3{margin:0;font-size:1.05rem;flex:1}
.rank{color:var(--mut);font-weight:700}.score{font-size:1.4rem;font-weight:800}.score small{font-size:.75rem;color:var(--mut);font-weight:500}
.badge{padding:.15rem .6rem;border-radius:99px;font-size:.78rem;font-weight:700}
.badge.A{background:var(--abg);color:var(--a)}.badge.B{background:var(--bbg);color:var(--b)}.badge.C{background:var(--cbg);color:var(--c)}
.bars{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.6rem;margin:.8rem 0}
.bar span{font-size:.75rem;color:var(--mut);display:flex;justify-content:space-between}
.bar div{height:6px;background:var(--cbg);border-radius:99px;margin-top:3px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--brand),var(--brand2));border-radius:99px}
.raisons{margin:.2rem 0;font-size:.85rem;color:var(--mut)}
details{margin-top:.5rem}summary{cursor:pointer;color:var(--brand);font-weight:600;font-size:.88rem}
dl{display:grid;grid-template-columns:130px 1fr;gap:.3rem .8rem;font-size:.88rem}dt{color:var(--mut)}dd{margin:0;word-break:break-word}
blockquote{margin:.6rem 0 0;padding:.7rem 1rem;background:var(--bg);border-left:3px solid var(--brand);border-radius:6px;font-size:.88rem;white-space:pre-wrap}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.6rem;border-bottom:1px solid var(--line);font-size:.9rem;vertical-align:top}
.mut{color:var(--mut);font-size:.85rem}.ok{text-align:center;padding:2rem 1rem}.ok h2{margin-top:0}
.cvbox{padding:1rem;border:2px dashed #c7d2fe;border-radius:12px;background:#f5f7ff}
.auto{background:#eef2ff!important;border-color:#a5b4fc!important}
#cvmsg:not(:empty){padding:.7rem 1rem;border-radius:9px;background:#eef2ff;color:#3730a3;font-size:.9rem}
#cvmsg.err{background:var(--errbg);color:var(--err)}
.hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
"""


def e(x):
    return html.escape(str(x), quote=True)


def layout(titre, sous_titre, corps, nav=""):
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(titre)} · Talent Engine</title><style>{CSS}</style></head><body>
<header><div class="in"><h1>{e(titre)}</h1><p>{e(sous_titre)}</p>{nav}</div></header>
<main>{corps}</main></body></html>"""


NAV_PUBLIC = '<nav><a href="/">Candidater</a><a href="/scoring">Comment sont évalués les profils ?</a></nav>'


# ----------------------------------------------------------------- donnees
def lire_lignes():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def parse_multipart(ctype, body):
    """Decode un formulaire multipart/form-data -> (champs texte, fichiers {nom: (nom_fichier, octets)})."""
    msg = email.message_from_bytes(b"Content-Type: " + ctype.encode("latin-1", "replace") + b"\r\n\r\n" + body,
                                   policy=email.policy.default)
    champs, fichiers = {}, {}
    if not msg.is_multipart():
        return champs, fichiers
    for part in msg.iter_parts():
        nom = part.get_param("name", header="content-disposition")
        if not nom:
            continue
        data = part.get_payload(decode=True) or b""
        fn = part.get_filename()
        if fn is not None:
            if fn and data:
                fichiers[nom] = (fn, data)
        else:
            champs[nom] = data.decode("utf-8", "replace")
    return champs, fichiers


def valider_cv(nom_fichier, data):
    """Verifie extension, taille et signature du fichier. -> (extension, erreur)."""
    ext = os.path.splitext(nom_fichier.lower())[1]
    if ext not in CV_TYPES:
        return "", "Format de CV non accepté : utilisez un PDF, DOC ou DOCX."
    if len(data) > CV_MAX:
        return "", "CV trop volumineux (3 Mo maximum)."
    ok = {".pdf": b"%PDF" in data[:1024], ".docx": data.startswith(b"PK\x03\x04"),
          ".doc": data.startswith(b"\xd0\xcf\x11\xe0")}[ext]
    if not ok:
        return "", f"Ce fichier ne ressemble pas à un vrai {ext[1:].upper()}."
    return ext, ""


def enregistrer_cv(nom_fichier, data):
    """Valide puis stocke sous un nom aleatoire. -> (nom_stocke, erreur)."""
    ext, err = valider_cv(nom_fichier, data)
    if err:
        return "", err
    os.makedirs(CV_DIR, mode=0o700, exist_ok=True)
    nom = secrets.token_hex(16) + ext   # le nom d'origine n'est jamais utilise sur le disque
    with open(os.path.join(CV_DIR, nom), "wb") as f:
        f.write(data)
    return nom, ""


def ajouter_candidature(ligne, cv=""):
    """Ajoute une ligne au CSV (ecriture atomique ; migre l'ancien format sans colonne cv)."""
    with LOCK:
        lignes = lire_lignes()
        if not cv:  # pas de nouveau CV : on garde celui d'une candidature precedente du meme email
            for l in reversed(lignes):
                if (l.get("email") or "").strip().lower() == ligne["email"].lower() and l.get("cv"):
                    cv = l["cv"]
                    break
        tous = [{k: (l.get(k) or "") for k in FIELDNAMES} for l in lignes] + [dict(ligne, cv=cv)]
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            w.writeheader()
            w.writerows(tous)
        os.replace(tmp, DATA_FILE)


def cellule_sure(v):
    """Neutralise l'injection de formules (Excel/Sheets) dans les exports CSV."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


# ----------------------------------------------------------------- pages publiques
SCRIPT_CV = """<script>
(function () {
  var form = document.getElementById('candidature');
  var input = form.querySelector('input[name=cv]');
  var msg = document.getElementById('cvmsg');
  var LIBELLES = {nom: 'nom', email: 'email', competences: 'compétences', annees_experience: "années d'expérience",
                  nb_projets: 'projets', lien_portfolio: 'lien'};
  // un champ modifie a la main n'est jamais ecrase par le pre-remplissage
  form.addEventListener('input', function (e) { if (e.target.name !== 'cv') e.target.dataset.touched = '1'; });
  function info(texte, erreur) { msg.textContent = texte; msg.className = erreur ? 'err' : ''; }
  input.addEventListener('change', function () {
    var f = input.files[0];
    if (!f) { info(''); return; }
    if (f.size > 3 * 1024 * 1024) { info('CV trop volumineux (3 Mo maximum).', true); return; }
    info('Lecture du CV…');
    var fd = new FormData(); fd.append('cv', f);
    fetch('/parse-cv', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (x) {
        if (!x.ok) { info(x.d.erreur || 'Lecture impossible.', true); return; }
        if (x.d.info) { info(x.d.info); return; }
        var remplis = [];
        Object.keys(x.d.champs).forEach(function (nom) {
          var v = x.d.champs[nom], el = form.elements[nom];
          if (!el || v === '' || v === 0 || el.dataset.touched) return;
          el.value = v; el.classList.add('auto'); remplis.push(LIBELLES[nom] || nom);
        });
        info(remplis.length
          ? 'Champs pré-remplis depuis votre CV : ' + remplis.join(', ') + '. Vérifiez-les et corrigez si besoin ; complétez aussi « Pourquoi ce programme ? ».'
          : "Nous n'avons rien pu extraire de ce CV : remplissez le formulaire à la main (le CV sera quand même joint).");
      })
      .catch(function () { info('Lecture impossible : remplissez le formulaire à la main (le CV sera quand même joint).', true); });
  });
})();
</script>"""


def page_formulaire(v=None, erreur=""):
    v = v or {}
    g = lambda k, d="": e(v.get(k, d))
    sel = lambda val: " selected" if v.get("disponibilite", "oui") == val else ""
    alerte = f'<div class="alert err">{e(erreur)}</div>' if erreur else ""
    corps = f"""<div class="panel">{alerte}
<form method="post" action="/submit" enctype="multipart/form-data" id="candidature">
<label class="cvbox">Commencez par votre CV <small>PDF ou Word, 3 Mo maximum (facultatif) — nous pré-remplissons le formulaire pour vous, vous pouvez tout corriger</small>
<input name="cv" type="file" accept=".pdf,.doc,.docx,application/pdf"></label>
<div id="cvmsg" role="status" aria-live="polite"></div>
<div class="row">
<label>Nom complet <input name="nom" required maxlength="100" value="{g('nom')}"></label>
<label>Email <input name="email" type="email" required maxlength="150" value="{g('email')}"></label></div>
<label>Compétences <small>séparées par des points-virgules</small>
<input name="competences" placeholder="Python; SQL; Git; React" maxlength="300" value="{g('competences')}"></label>
<div class="row">
<label>Années d'expérience <input name="annees_experience" type="number" min="0" max="50" step="0.5" value="{g('annees_experience','0')}"></label>
<label>Projets réalisés <input name="nb_projets" type="number" min="0" max="100" value="{g('nb_projets','0')}"></label></div>
<label>Lien GitHub / portfolio <small>un lien vérifiable compte dans l'évaluation</small>
<input name="lien_portfolio" maxlength="200" placeholder="https://github.com/..." value="{g('lien_portfolio')}"></label>
<label>Pourquoi ce programme ? <small>quelques lignes sur ce que vous voulez apprendre et apporter</small>
<textarea name="motivation" rows="5" maxlength="2000">{g('motivation')}</textarea></label>
<label>Disponible pour le démarrage du 2 novembre ?
<select name="disponibilite"><option value="oui"{sel('oui')}>Oui</option>
<option value="partiel"{sel('partiel')}>Partiellement</option><option value="non"{sel('non')}>Non</option></select></label>
<div class="hp" aria-hidden="true"><label>Ne pas remplir <input name="site" tabindex="-1" autocomplete="off"></label></div>
<button>Envoyer ma candidature</button></form></div>{SCRIPT_CV}"""
    return layout("Candidater à SKULLVI", "Remplissez le formulaire : votre dossier est évalué selon une grille transparente.", corps, NAV_PUBLIC)


def page_merci():
    corps = """<div class="panel ok"><h2>Candidature reçue ✔</h2>
<p>Merci ! Votre dossier a bien été enregistré et sera examiné.</p>
<p class="mut">Si vous renvoyez le formulaire avec le même email, c'est votre dernière version qui sera retenue.</p>
<a class="btn sec" href="/scoring">Voir comment les profils sont évalués</a></div>"""
    return layout("Merci !", "Votre candidature a été envoyée.", corps, NAV_PUBLIC)


def page_scoring():
    lignes = "".join(
        f"<tr><td><b>{e(LIBELLES[k])}</b></td><td>{pts} pts</td><td>{e(EXPLICATIONS[k])}</td></tr>"
        for k, pts in te.POIDS.items())
    corps = f"""<div class="panel"><p>Chaque candidature reçoit un score sur <b>100</b>. Chaque critère est <b>plafonné</b> :
aucun ne peut dominer seul. Le score sert à <b>trier la file d'examen</b> ; un humain décide toujours.</p>
<table><tr><th>Critère</th><th>Poids</th><th>Logique</th></tr>{lignes}</table></div>
<div class="panel"><b>Priorités</b><p>
<span class="badge A">A</span> ≥ {te.SEUIL_A} : à examiner en priorité &nbsp;
<span class="badge B">B</span> ≥ {te.SEUIL_B} : à examiner ensuite &nbsp;
<span class="badge C">C</span> &lt; {te.SEUIL_B} : à examiner si le temps le permet</p>
<p class="mut">Sont écartés avant scoring : dossiers sans nom ou sans email valide, et doublons (on garde la version la plus récente).</p></div>"""
    return layout("Grille d'évaluation", "Transparente, simple, explicable.", corps, NAV_PUBLIC)


# ----------------------------------------------------------------- admin
def lien_html(lien):
    if lien.lower().startswith(("http://", "https://")):
        return f'<a href="{e(lien)}" target="_blank" rel="noopener noreferrer">{e(lien)}</a>'
    return e(lien) or "—"


def carte(i, c, cv=""):
    barres = "".join(
        f'<div class="bar"><span>{e(LIBELLES[k])}<b>{v}/{te.POIDS[k]}</b></span>'
        f'<div><i style="width:{min(100, v / te.POIDS[k] * 100):.0f}%"></i></div></div>'
        for k, v in c.detail.items())
    raisons = f'<p class="raisons">{e(" · ".join(c.raisons))}</p>' if c.raisons else ""
    mot = f"<blockquote>{e(c.motivation)}</blockquote>" if c.motivation else ""
    cv_ok = bool(cv and CV_NOM_RE.match(cv))
    cv_lien = f'<a href="/admin/cv/{e(cv)}">Télécharger le CV</a>' if cv_ok else "Non fourni"
    cv_tag = '<span class="badge C">📎 CV</span>' if cv_ok else ""
    return f"""<article class="card"><div class="head"><span class="rank">#{i}</span><h3>{e(c.nom)}</h3>
{cv_tag}<span class="badge {c.priorite}">Priorité {c.priorite}</span><span class="score">{c.score}<small>/100</small></span></div>
<div class="bars">{barres}</div>{raisons}
<details><summary>Voir le dossier complet</summary><dl>
<dt>Email</dt><dd><a href="mailto:{e(c.email)}">{e(c.email)}</a></dd>
<dt>Compétences</dt><dd>{e(', '.join(c.competences)) or '—'}</dd>
<dt>Expérience</dt><dd>{c.annees_experience:g} an(s)</dd>
<dt>Projets</dt><dd>{c.nb_projets}</dd>
<dt>Lien</dt><dd>{lien_html(c.lien_portfolio)}</dd>
<dt>Disponibilité</dt><dd>{e(c.disponibilite)}</dd>
<dt>CV</dt><dd>{cv_lien}</dd></dl>{mot}</details></article>"""


def page_admin(prio="", recherche=""):
    lignes = lire_lignes()
    brut = [te.ligne_vers_candidat(l) for l in lignes]
    cvs = {(l.get("email") or "").strip().lower(): l["cv"] for l in lignes if l.get("cv")}
    classes, rejetes = te.traiter(brut)
    nb = {p: sum(1 for c in classes if c.priorite == p) for p in "ABC"}
    rang = list(enumerate(classes, 1))
    if prio in ("A", "B", "C"):
        rang = [(i, c) for i, c in rang if c.priorite == prio]
    if recherche:
        r = recherche.lower()
        rang = [(i, c) for i, c in rang if r in (c.nom + " " + c.email + " " + " ".join(c.competences)).lower()]
    chips = "".join(
        f'<a class="chip{" on" if prio == p else ""}" href="/admin?prio={p}&q={e(recherche)}">{lab}</a>'
        for p, lab in (("", "Tous"), ("A", "Priorité A"), ("B", "B"), ("C", "C")))
    cartes = "".join(carte(i, c, cvs.get(c.email, "")) for i, c in rang) or '<div class="panel mut">Aucune candidature à afficher.</div>'
    ecartes = "".join(
        f"<tr><td>{e(c.nom or '(sans nom)')}</td><td>{e(c.email)}</td><td>{e(c.statut)}</td></tr>" for c in rejetes)
    bloc_ecartes = (f'<div class="panel"><b>Dossiers écartés ({len(rejetes)})</b><table>'
                    f"<tr><th>Nom</th><th>Email</th><th>Motif</th></tr>{ecartes}</table></div>") if rejetes else ""
    corps = f"""<div class="stats">
<div class="stat"><b>{len(brut)}</b><span>reçues</span></div>
<div class="stat"><b>{len(classes)}</b><span>qualifiées</span></div>
<div class="stat"><b style="color:var(--a)">{nb['A']}</b><span>priorité A</span></div>
<div class="stat"><b style="color:var(--b)">{nb['B']}</b><span>priorité B</span></div>
<div class="stat"><b>{nb['C']}</b><span>priorité C</span></div>
<div class="stat"><b>{len(rejetes)}</b><span>écartées</span></div></div>
<div class="tools">{chips}
<form method="get" action="/admin"><input type="hidden" name="prio" value="{e(prio)}">
<input name="q" placeholder="Rechercher nom, email, compétence…" value="{e(recherche)}"><button>OK</button></form>
<a class="btn sec" href="/admin/export.csv">Exporter CSV</a></div>
{cartes}{bloc_ecartes}"""
    nav = '<nav><a href="/">Formulaire public</a><a href="/scoring">Grille de scoring</a></nav>'
    return layout("Espace administrateur", "Candidatures classées par score, avec le détail de chaque critère.", corps, nav)


def export_csv(base=""):
    lignes = lire_lignes()
    cvs = {(l.get("email") or "").strip().lower(): l["cv"] for l in lignes if l.get("cv")}
    classes, _ = te.traiter([te.ligne_vers_candidat(l) for l in lignes])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rang", "priorite", "score", "nom", "email", "competences", "annees_experience",
                "nb_projets", "lien", "disponibilite", "cv_lien"] + ["score_" + k for k in te.POIDS] + ["raisons", "motivation"])
    for i, c in enumerate(classes, 1):
        w.writerow([cellule_sure(x) for x in
                    [i, c.priorite, c.score, c.nom, c.email, "; ".join(c.competences), c.annees_experience,
                     c.nb_projets, c.lien_portfolio, c.disponibilite,
                     f"{base}/admin/cv/{cvs[c.email]}" if c.email in cvs else ""]
                    + [c.detail[k] for k in te.POIDS] + ["; ".join(c.raisons), c.motivation]])
    return buf.getvalue()


# ----------------------------------------------------------------- serveur
class Handler(BaseHTTPRequestHandler):
    def _envoyer(self, code, corps, ctype="text/html; charset=utf-8", extra=None):
        self._envoyer_bytes(code, corps.encode("utf-8"), ctype, extra)

    def _servir_cv(self, nom):
        chemin = os.path.join(CV_DIR, nom)
        if not CV_NOM_RE.match(nom) or not os.path.isfile(chemin):
            return self._envoyer(404, "Introuvable", "text/plain; charset=utf-8")
        with open(chemin, "rb") as f:
            data = f.read()
        self._envoyer_bytes(200, data, CV_TYPES[os.path.splitext(nom)[1]],
                            {"Content-Disposition": f'attachment; filename="cv-{nom}"', "Cache-Control": "no-store"})

    def _envoyer_bytes(self, code, data, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _ip(self):
        return self.headers.get("X-Real-IP") or self.client_address[0]

    def _admin_ok(self):
        """True si autorise. Sinon envoie la reponse (503/401) et renvoie False."""
        if not ADMIN_PASSWORD:
            self._envoyer(503, "Espace admin desactive : definir ADMIN_PASSWORD.", "text/plain; charset=utf-8")
            return False
        try:
            kind, _, b64 = (self.headers.get("Authorization") or "").partition(" ")
            user, _, pwd = base64.b64decode(b64).decode("utf-8").partition(":")
            ok = kind.lower() == "basic" and \
                hmac.compare_digest(user.encode(), ADMIN_USER.encode()) and \
                hmac.compare_digest(pwd.encode(), ADMIN_PASSWORD.encode())
        except Exception:
            ok = False
        if not ok:
            time.sleep(1)  # freine le bruteforce
            self._envoyer(401, "Authentification requise", "text/plain; charset=utf-8",
                          {"WWW-Authenticate": 'Basic realm="Talent Engine admin", charset="UTF-8"'})
        return ok

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self._envoyer(200, page_formulaire())
        elif u.path == "/merci":
            self._envoyer(200, page_merci())
        elif u.path == "/scoring":
            self._envoyer(200, page_scoring())
        elif u.path == "/health":
            self._envoyer(200, "ok", "text/plain")
        elif u.path == "/admin":
            if self._admin_ok():
                self._envoyer(200, page_admin(q.get("prio", [""])[0], q.get("q", [""])[0].strip()[:100]),
                              extra={"Cache-Control": "no-store"})
        elif u.path == "/admin/export.csv":
            if self._admin_ok():
                self._envoyer(200, export_csv("https://" + (self.headers.get("Host") or "")), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="classement.csv"',
                               "Cache-Control": "no-store"})
        elif u.path.startswith("/admin/cv/"):
            if self._admin_ok():
                self._servir_cv(u.path.rsplit("/", 1)[1])
        else:
            self._envoyer(404, "Introuvable", "text/plain; charset=utf-8")

    def _parse_cv(self):
        """Lit un CV (sans le stocker) et renvoie des valeurs suggerees pour le formulaire (JSON)."""
        def rep(code, obj):
            self._envoyer(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8",
                          {"Cache-Control": "no-store"})
        n = int(self.headers.get("Content-Length") or 0)
        ctype = self.headers.get("Content-Type") or ""
        if n > MAX_UPLOAD:
            self.close_connection = True
            return rep(413, {"erreur": "CV trop volumineux (3 Mo maximum)."})
        if not ctype.lower().startswith("multipart/form-data"):
            return rep(400, {"erreur": "Requête invalide."})
        now, ip = time.time(), self._ip()
        PARSES[ip] = [t for t in PARSES[ip] if now - t < RATE_WINDOW]
        if len(PARSES[ip]) >= PARSE_MAX:
            return rep(429, {"erreur": "Trop de lectures de CV depuis cette adresse : remplissez à la main ou réessayez plus tard."})
        PARSES[ip].append(now)
        _, fichiers = parse_multipart(ctype, self.rfile.read(n))
        f = fichiers.get("cv")
        if not f:
            return rep(400, {"erreur": "Aucun fichier reçu."})
        _, err = valider_cv(*f)
        if err:
            return rep(400, {"erreur": err})
        texte, err = cv_parser.extraire_texte(*f)
        if err:
            return rep(200, {"info": err, "champs": {}})   # fichier valide mais illisible : pas une erreur
        rep(200, {"champs": cv_parser.analyser(texte)})

    def do_POST(self):
        if urlparse(self.path).path == "/parse-cv":
            return self._parse_cv()
        if urlparse(self.path).path != "/submit":
            return self._envoyer(404, "Introuvable", "text/plain; charset=utf-8")
        n = int(self.headers.get("Content-Length") or 0)
        ctype = self.headers.get("Content-Type") or ""
        multipart = ctype.lower().startswith("multipart/form-data")
        if n > (MAX_UPLOAD if multipart else MAX_BODY):
            self.close_connection = True
            return self._envoyer(413, page_formulaire(None, "Envoi trop volumineux (CV : 3 Mo maximum)."))
        corps = self.rfile.read(n)
        cv_file = None
        if multipart:
            form, fichiers = parse_multipart(ctype, corps)
            cv_file = fichiers.get("cv")
        else:
            form = {k: v[0] for k, v in parse_qs(corps.decode("utf-8", "replace")).items()}
        if form.get("site"):  # piege a robots : champ cache rempli -> on ignore sans rien dire
            return self._envoyer(303, "", "text/plain", {"Location": "/merci"})
        now, ip = time.time(), self._ip()
        ENVOIS[ip] = [t for t in ENVOIS[ip] if now - t < RATE_WINDOW]
        if len(ENVOIS[ip]) >= RATE_MAX:
            return self._envoyer(429, page_formulaire(form, "Trop d'envois depuis cette adresse. Réessayez dans quelques minutes."))
        ligne = {k: form.get(k, "").strip() for k in CHAMPS}
        ok, motif = te.valider(te.ligne_vers_candidat(ligne))
        if not ok:
            return self._envoyer(400, page_formulaire(ligne, f"Candidature refusée : {motif}."))
        cv_nom = ""
        if cv_file:
            cv_nom, err = enregistrer_cv(*cv_file)
            if err:
                return self._envoyer(400, page_formulaire(ligne, err))
        ENVOIS[ip].append(now)
        ajouter_candidature(ligne, cv_nom)
        self._envoyer(303, "", "text/plain", {"Location": "/merci"})

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    print(f"Talent Engine web sur http://{HOST}:{PORT}  (donnees : {DATA_FILE}) "
          f"admin={'actif' if ADMIN_PASSWORD else 'DESACTIVE (pas de ADMIN_PASSWORD)'}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
