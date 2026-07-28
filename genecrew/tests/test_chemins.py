"""Un rapport ne doit jamais effacer celui d'un run précédent."""

import time

from genecrew.chemins import chemin_libre


def _horloge(hhmmss):
    """Horloge figée : le test ne doit pas dépendre de l'heure qu'il est."""
    return lambda: time.strptime(hhmmss, "%H%M%S")


def test_chemin_inchange_quand_il_est_libre(tmp_path):
    """Cas courant : aucun bruit ajouté au nom tant qu'il n'y a rien à protéger."""
    cible = tmp_path / "2026-07-27_lieux_wiki_ecritures.md"
    assert chemin_libre(cible, horloge=_horloge("224757")) == cible


def test_un_second_run_n_ecrase_pas_le_premier(tmp_path):
    """C'est le défaut mesuré : un run de 15 lieux a effacé le rapport de 591 images."""
    cible = tmp_path / "2026-07-27_lieux_wiki_ecritures.md"
    cible.write_text("591 images", encoding="utf-8")

    second = chemin_libre(cible, horloge=_horloge("224757"))

    assert second != cible
    assert cible.read_text(encoding="utf-8") == "591 images", "le premier a été touché"
    assert second.name == "2026-07-27_lieux_wiki_ecritures_224757.md"


def test_la_reservation_est_atomique(tmp_path):
    """Deux appels sans écriture intercalée doivent déjà différer.

    Un simple `exists()` laisse une fenêtre entre le choix du nom et l'écriture, qui
    survient bien plus tard chez l'appelant : deux runs se terminant ensemble
    choisiraient le même fichier — le dégât même que ce module doit empêcher. La
    réservation crée donc le fichier sur-le-champ, en `O_CREAT | O_EXCL`.
    """
    cible = tmp_path / "rapport.md"
    h = _horloge("120000")

    premier = chemin_libre(cible, horloge=h)
    deuxieme = chemin_libre(cible, horloge=h)
    troisieme = chemin_libre(cible, horloge=h)

    assert len({premier, deuxieme, troisieme}) == 3, (premier, deuxieme, troisieme)
    assert all(p.exists() for p in (premier, deuxieme, troisieme))


def test_le_chemin_reserve_est_vide_et_ecrasable_par_l_appelant(tmp_path):
    """La réservation ne doit pas gêner l'écriture qu'elle protège."""
    cible = tmp_path / "rapport.md"
    reserve = chemin_libre(cible, horloge=_horloge("120000"))
    assert reserve.read_text(encoding="utf-8") == ""
    reserve.write_text("contenu réel", encoding="utf-8")
    assert reserve.read_text(encoding="utf-8") == "contenu réel"


def test_l_extension_est_preservee(tmp_path):
    """Les YAML relus sont consommés par `apply` : leur suffixe ne doit pas bouger."""
    cible = tmp_path / "2026-07-27_propositions_lieux_all.yaml"
    cible.write_text("- a", encoding="utf-8")
    assert chemin_libre(cible, horloge=_horloge("090000")).suffix == ".yaml"


def test_le_repertoire_manquant_est_cree(tmp_path):
    """Réserver suppose de créer : le helper ne peut pas laisser ce soin à l'appelant."""
    cible = tmp_path / "pas_encore" / "rapport.md"
    reserve = chemin_libre(cible, horloge=_horloge("120000"))
    assert reserve == cible and cible.exists()
