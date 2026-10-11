import unittest

from talent_engine import (
    ligne_vers_candidat, lire_csv, traiter, valider, normaliser_competences,
    _nombre, noter, POIDS, SEUIL_A,
)


def cand(**kw):
    base = dict(nom="Test", email="t@example.com", competences="python", annees_experience="1",
                nb_projets="1", lien_portfolio="", motivation="", disponibilite="oui")
    base.update(kw)
    return ligne_vers_candidat(base)


class TestNettoyage(unittest.TestCase):
    def test_nombre_robuste(self):
        self.assertEqual(_nombre("2,5 ans"), 2.5)
        self.assertEqual(_nombre("abc"), 0.0)
        self.assertEqual(_nombre(None), 0.0)
        self.assertEqual(_nombre("-3"), 3.0)  # le signe est ignore, jamais negatif

    def test_competences_alias_et_doublons(self):
        self.assertEqual(normaliser_competences("Python; JS, js ; Node.js"),
                         ["python", "javascript", "node"])
        self.assertEqual(normaliser_competences(""), [])


class TestValidation(unittest.TestCase):
    def test_email_invalide(self):
        self.assertFalse(valider(cand(email="pas-un-email"))[0])

    def test_nom_manquant(self):
        self.assertFalse(valider(cand(nom=""))[0])

    def test_valide(self):
        self.assertTrue(valider(cand())[0])


class TestScoring(unittest.TestCase):
    def test_score_borne_0_100(self):
        vide = noter(cand(competences="", annees_experience="0", nb_projets="0", disponibilite="non"))
        self.assertEqual(vide.score, 0.0)
        max_ = noter(cand(
            competences="python;sql;git;flask;api;docker;react;node",
            annees_experience="10", nb_projets="20", lien_portfolio="https://github.com/x",
            motivation=("Je veux apprendre, contribuer, construire un projet en equipe " * 5),
        ))
        self.assertLessEqual(max_.score, 100.0)
        self.assertAlmostEqual(max_.score, 100.0, places=1)

    def test_poids_somment_a_100(self):
        self.assertEqual(sum(POIDS.values()), 100)

    def test_lien_verifiable_augmente_score(self):
        sans = noter(cand(lien_portfolio=""))
        avec = noter(cand(lien_portfolio="https://github.com/x"))
        self.assertGreater(avec.score, sans.score)

    def test_priorite(self):
        fort = noter(cand(competences="python;sql;git;flask;api;docker;react",
                          annees_experience="3", nb_projets="4",
                          lien_portfolio="https://github.com/x",
                          motivation="Je veux apprendre et contribuer en equipe sur un projet. " * 4))
        self.assertGreaterEqual(fort.score, SEUIL_A)
        self.assertEqual(fort.priorite, "A")
        faible = noter(cand(competences="excel", annees_experience="0", nb_projets="0",
                            disponibilite="non"))
        self.assertEqual(faible.priorite, "C")


class TestPipeline(unittest.TestCase):
    def test_doublon_garde_le_dernier(self):
        a = cand(nom="Awa", email="a@example.com", nb_projets="1")
        b = cand(nom="Awa", email="A@example.com", nb_projets="4")
        classes, rejetes = traiter([a, b])
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0].nb_projets, 4)
        self.assertEqual(len(rejetes), 1)

    def test_tri_decroissant_et_deterministe(self):
        faible = cand(nom="Faible", email="f@example.com", competences="excel", nb_projets="0")
        fort = cand(nom="Fort", email="g@example.com",
                    competences="python;sql;git;api", nb_projets="3",
                    lien_portfolio="https://github.com/x")
        classes, _ = traiter([faible, fort])
        self.assertEqual([c.nom for c in classes], ["Fort", "Faible"])

    def test_liste_vide(self):
        self.assertEqual(traiter([]), ([], []))

    def test_fichier_exemple(self):
        classes, rejetes = traiter(lire_csv("candidatures_exemple.csv"))
        noms = [c.nom for c in classes]
        self.assertEqual(noms[0], "Awa Koné")           # meilleur profil, version mise a jour
        self.assertEqual(noms.count("Awa Koné"), 1)      # doublon elimine
        self.assertNotIn("Ibrahim Traoré", noms)         # email invalide
        self.assertEqual(len(rejetes), 3)                # email invalide + sans nom + doublon


if __name__ == "__main__":
    unittest.main()
