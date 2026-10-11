import datetime
import io
import unittest
import zipfile

import cv_parser as cp

try:
    import reportlab  # noqa: F401  (sert seulement a fabriquer un PDF de test)
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

CV_EXEMPLE = """EVARISTE KOUAME
Développeur web
evariste.kouame@example.com | +225 07 00 00 00 00
github.com/evaristek | https://www.linkedin.com/in/evariste

PROFIL
Développeur curieux, j'aime apprendre.

EXPÉRIENCE PROFESSIONNELLE
Développeur Python - Société X          2022 - 2024
• API de gestion de stocks en Flask
Stagiaire - Société Y                   Jan 2021 - Mars 2021

FORMATION
Licence informatique 2019 - 2022

COMPÉTENCES
Python, JavaScript, SQL, Git, Docker, React, Node.js, Excel

PROJETS
• Talent Engine - moteur de scoring de candidatures
• Site e-commerce en React
- Application mobile de suivi
LANGUES
Français, Anglais
"""


def docx_octets(texte):
    paras = "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in texte.splitlines())
    xml = f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{paras}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def pdf_octets(texte):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ligne in texte.splitlines():
        c.drawString(40, y, ligne)
        y -= 14
    c.save()
    return buf.getvalue()


class TestAnalyse(unittest.TestCase):
    def setUp(self):
        self.r = cp.analyser(CV_EXEMPLE)

    def test_nom(self):
        self.assertEqual(self.r["nom"], "Evariste Kouame")

    def test_email(self):
        self.assertEqual(self.r["email"], "evariste.kouame@example.com")

    def test_lien_prefere_github(self):
        self.assertEqual(self.r["lien_portfolio"], "https://github.com/evaristek")

    def test_competences(self):
        comp = self.r["competences"].split("; ")
        for attendu in ["Python", "JavaScript", "SQL", "Git", "Docker", "React", "Node.js"]:
            self.assertIn(attendu, comp)
        self.assertNotIn("Excel", comp)           # hors liste cible
        self.assertNotIn("Java", comp)            # 'JavaScript' ne doit pas declencher 'Java'

    def test_experience_union_des_periodes(self):
        # 2022-2024 = 2 ans ; 2021 isole = 0,5 ; la formation (2019-2022) n'est PAS comptee
        self.assertEqual(self.r["annees_experience"], 2.5)

    def test_projets_par_puces(self):
        self.assertEqual(self.r["nb_projets"], 3)

    def test_experience_explicite(self):
        self.assertEqual(cp.analyser("Jean Dupont\n5 ans d'expérience en développement")["annees_experience"], 5.0)

    def test_en_cours(self):
        txt = "Jean Dupont\nEXPÉRIENCE\nDev - X  2024 - présent\nFORMATION\nX"
        attendu = datetime.date.today().year - 2024
        self.assertEqual(cp.analyser(txt)["annees_experience"], float(attendu))

    def test_texte_vide_ou_hostile(self):
        r = cp.analyser("")
        self.assertEqual(r["nom"], "")
        self.assertEqual(r["annees_experience"], 0.0)
        self.assertEqual(r["nb_projets"], 0)
        cp.analyser("<script>alert(1)</script>" * 500)   # ne plante pas

    def test_nom_pas_un_titre(self):
        self.assertEqual(cp.trouver_nom("Curriculum Vitae\nDéveloppeur Web\nKonan Aya\n"), "Konan Aya")
        self.assertEqual(cp.trouver_nom("Développeur Full Stack\n"), "")


class TestExtraction(unittest.TestCase):
    def test_docx(self):
        texte, err = cp.extraire_texte("cv.docx", docx_octets(CV_EXEMPLE))
        self.assertEqual(err, "")
        self.assertEqual(cp.analyser(texte)["email"], "evariste.kouame@example.com")

    @unittest.skipUnless(HAS_REPORTLAB, "reportlab absent : test PDF ignore")
    def test_pdf(self):
        texte, err = cp.extraire_texte("cv.pdf", pdf_octets(CV_EXEMPLE))
        self.assertEqual(err, "")
        r = cp.analyser(texte)
        self.assertEqual(r["email"], "evariste.kouame@example.com")
        self.assertIn("Python", r["competences"])
        self.assertEqual(r["nb_projets"], 3)      # les puces des PDF sortent souvent en caracteres etranges

    def test_doc_ancien_format_message_clair(self):
        texte, err = cp.extraire_texte("cv.doc", b"\xd0\xcf\x11\xe0" + b"0" * 100)
        self.assertEqual(texte, "")
        self.assertIn("à la main", err)

    def test_pdf_corrompu(self):
        texte, err = cp.extraire_texte("cv.pdf", b"%PDF-1.4 n'importe quoi")
        self.assertEqual(texte, "")
        self.assertTrue(err)

    def test_docx_corrompu(self):
        texte, err = cp.extraire_texte("cv.docx", b"PK\x03\x04pas un zip")
        self.assertEqual(texte, "")
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
