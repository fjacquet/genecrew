"""Un rapport ne doit jamais effacer celui d'un run précédent."""

from pathlib import Path

from genecrew.chemins import chemin_libre


def _horloge(hhmmss):
    """Horloge figée : le test ne doit pas dépendre de l'heure qu'il est."""
    import time

    return lambda: time.strptime(hhmmss, "%H%M%S")


def test_chemin_inchange_quand_il_est_libre(tmp_path):
    """Cas courant : aucun bruit ajouté au nom tant que rien n'existe."""
    cible = tmp_path / "2026-07-27_lieux_wiki_ecritures.md"
    assert chemin_libre(cible, horloge=_horloge("224757")) == cible


def test_un_second_run_n_ecrase_pas_le_premier(tmp_path):
    """C'est le défaut mesuré : un run de 15 lieux a effacé le rapport de 591 images."""
    cible = tmp_path / "2026-07-27_lieux_wiki_ecritures.md"
    cible.write_text("591 images", encoding="utf-8")

    second = chemin_libre(cible, horloge=_horloge("224757"))

    assert second != cible
    assert not second.exists()
    assert cible.read_text(encoding="utf-8") == "591 images", "le premier a été touché"
    assert second.name == "2026-07-27_lieux_wiki_ecritures_224757.md"


def test_l_extension_est_preservee(tmp_path):
    """Les YAML relus sont consommés par `apply` : leur suffixe ne doit pas bouger."""
    cible = tmp_path / "2026-07-27_propositions_lieux_all.yaml"
    cible.write_text("- a", encoding="utf-8")
    assert chemin_libre(cible, horloge=_horloge("090000")).suffix == ".yaml"


def test_deux_collisions_dans_la_meme_seconde_restent_distinctes(tmp_path):
    """Deux runs bornés peuvent finir dans la même seconde ; l'heure seule ne suffit pas."""
    cible = tmp_path / "rapport.md"
    cible.write_text("premier", encoding="utf-8")
    h = _horloge("120000")

    deuxieme = chemin_libre(cible, horloge=h)
    deuxieme.write_text("deuxième", encoding="utf-8")
    troisieme = chemin_libre(cible, horloge=h)

    assert len({cible, deuxieme, troisieme}) == 3, (cible, deuxieme, troisieme)
    assert not troisieme.exists()


def test_un_repertoire_absent_ne_fait_pas_echouer(tmp_path):
    """Le helper décide d'un nom ; créer le dossier reste au code appelant."""
    cible = tmp_path / "pas_encore" / "rapport.md"
    assert chemin_libre(cible, horloge=_horloge("120000")) == cible
