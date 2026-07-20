"""Tests hors-ligne du moteur d'appariement des relevés (pur, sans réseau)."""

from typing import get_args

import pytest
from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from pydantic import ValidationError

from genecrew.releves import (
    FACTEURS_FORTS,
    POIDS,
    Appariement,
    FacteurReleve,
    PersonneLiee,
    ReleveIndexe,
    apparier,
    candidats_blocage,
    est_rare,
    rarete_patronymes,
)


def _p(gramps_id, surname, given, **kw):
    return PersonFacts(gramps_id=gramps_id, handle=f"h{gramps_id}",
                       name=f"{given} {surname}", surname=surname, given=given,
                       sex=kw.pop("sex", "U"), **kw)


def test_releve_indexe_minimal():
    r = ReleveIndexe(
        fonds="Cercle Généalogique du Haut-Berry", reference="106710046161418286",
        sujet_nom="JACQUET", sujet_prenom="Rose", evenement_type="Death",
        texte_brut="Rose JACQUET\nLe 10 décembre 1894",
    )
    assert r.evenement_date == ""
    assert r.personnes_liees == []


def test_personne_liee_porte_son_role():
    p = PersonneLiee(nom="Pierre JACQUET", role="père", detail="décédé avant 1894")
    assert p.role == "père"


def test_facteur_hors_vocabulaire_refuse():
    """Vocabulaire fermé : « né en 1821 » ne doit pas pouvoir gonfler un score."""
    with pytest.raises(ValidationError):
        Appariement(verdict="net", facteurs=["né en 1821"])


def test_annee_approximative_est_un_facteur_distinct_de_la_date():
    """Règle projet : une année seule n'est jamais discriminante."""
    a = Appariement(verdict="gris", facteurs=["année approximative"])
    assert "date complète" not in a.facteurs


def test_vocabulaire_des_facteurs_reste_synchronise():
    """`FacteurReleve`, `POIDS` et `FACTEURS_FORTS` répètent le même vocabulaire à
    trois endroits ; un renommage ou un accent oublié dans un seul des trois ferait
    calculer des poids faux sans qu'aucune erreur ne se déclenche ailleurs."""
    vocabulaire = set(get_args(FacteurReleve))
    assert set(POIDS.keys()) == vocabulaire
    assert FACTEURS_FORTS <= vocabulaire


def test_rarete_est_une_fraction_de_l_arbre():
    people = [_p("I1", "JACQUET", "Rose"), _p("I2", "JACQUET", "Pierre"),
              _p("I3", "JACQUET", "Jean"), _p("I4", "VILLEPELLET", "Marie")]
    r = rarete_patronymes(people)
    assert r["JACQUET"] == 0.75
    assert r["VILLEPELLET"] == 0.25


def test_rarete_ignore_casse_et_accents():
    people = [_p("I1", "Jacquet", "Rose"), _p("I2", "JACQUET", "Pierre")]
    r = rarete_patronymes(people)
    assert r["JACQUET"] == 1.0


def test_est_rare_distingue_le_courant_du_rare():
    r = {"JACQUET": 0.75, "VILLEPELLET": 0.01}
    assert est_rare("VILLEPELLET", r) is True
    assert est_rare("JACQUET", r) is False


def test_patronyme_absent_de_l_arbre_n_est_pas_rare():
    """Absent ≠ rare : sans mesure, on n'accorde pas de poids fort."""
    assert est_rare("INCONNU", {"JACQUET": 0.75}) is False


def _releve(**kw):
    base = dict(fonds="CGHB", reference="106710046161418286", sujet_nom="JACQUET",
                sujet_prenom="Rose", evenement_type="Death", texte_brut="…")
    base.update(kw)
    return ReleveIndexe(**base)


def test_blocage_retient_le_patronyme_et_rejette_le_reste():
    people = [_p("I1", "JACQUET", "Rose"), _p("I2", "VILLEPELLET", "Marie")]
    assert [c.gramps_id for c in candidats_blocage(_releve(), people)] == ["I1"]


def test_blocage_tolere_casse_et_accents():
    people = [_p("I1", "Jacquèt", "Rose")]
    assert len(candidats_blocage(_releve(sujet_nom="JACQUET"), people)) == 1


def test_blocage_suit_les_variantes_de_graphie():
    """Sans table de variantes, « absent » voudrait dire « mal cherché »."""
    people = [_p("I1", "JACQUET", "Rose")]
    assert len(candidats_blocage(_releve(sujet_nom="JAQUET"), people)) == 1


def test_blocage_vide_quand_le_patronyme_est_inconnu():
    people = [_p("I1", "JACQUET", "Rose")]
    assert candidats_blocage(_releve(sujet_nom="MARTIN"), people) == []


def test_blocage_vide_quand_le_releve_n_a_pas_de_patronyme():
    """Un patronyme vide n'est pas une graphie : même si l'arbre contient une
    personne à patronyme vide (filiation inconnue, enfant naturel), on ne peut
    pas bloquer sur une absence de donnée des deux côtés."""
    people = [_p("I1", "", "Rose"), _p("I2", "JACQUET", "Pierre")]
    assert candidats_blocage(_releve(sujet_nom=""), people) == []


def test_blocage_vide_quand_le_patronyme_du_releve_est_blanc():
    """Un patronyme fait uniquement d'espaces n'est pas non plus une graphie :
    `_normaliser` le réduit à une chaîne vide, exactement comme une chaîne déjà
    vide au départ. Si `_normaliser` régressait (espaces mal réduits), ce test
    est celui qui le détecterait — le test voisin sur la chaîne littéralement
    vide ne l'aurait pas fait."""
    people = [_p("I1", "", "Rose"), _p("I2", "JACQUET", "Pierre")]
    assert candidats_blocage(_releve(sujet_nom="   "), people) == []


def test_blocage_ignore_les_personnes_a_patronyme_vide_quand_le_releve_en_a_un():
    """Un relevé au patronyme renseigné ne doit jamais retenir une personne à
    patronyme vide — ce cas passe déjà, mais on le verrouille pour ne pas
    régresser si `_cle_blocage` change un jour."""
    people = [_p("I1", "", "Rose"), _p("I2", "JACQUET", "Pierre")]
    assert [c.gramps_id for c in candidats_blocage(_releve(sujet_nom="JACQUET"), people)] == ["I2"]


def _ev(type_, jour=0, mois=0, annee=0, lieu="", modifier=0, dateval=None):
    """`EventFact` ne porte PAS de champ `date` : la source est `dateval`, au
    format Gramps [jour, mois, année, slash]. 0 = composante inconnue.

    Le lieu est produit sous sa forme RÉELLE : `place` porte la hiérarchie
    complète telle que Gramps la rend (« commune, département, pays ») et
    `place_name` la commune seule. Une fixture qui mettrait la commune nue dans
    `place` validerait une donnée que la source ne produit jamais — et
    masquerait le fait que comparer `place` à un lieu de relevé (une commune)
    échoue sur toutes les vraies données.
    """
    return EventFact(type=type_, dateval=dateval or [jour, mois, annee, False],
                     year=annee or None, modifier=modifier,
                     place=f"{lieu}, Cher, France" if lieu else "",
                     place_name=lieu,
                     sortval=1 if annee else 0)


def _mort(person, jour, mois, annee, lieu=""):
    person.death = _ev("Death", jour, mois, annee, lieu)
    return person


ROSE = _releve(evenement_date="1894-12-10", evenement_lieu="Saint-Martin-d'Auxigny",
               naissance_estimee=1821,
               personnes_liees=[PersonneLiee(nom="Pierre JACQUET", role="père"),
                                PersonneLiee(nom="Marie Anne VILLEPELLET", role="mère")])


def test_deux_facteurs_forts_donnent_net():
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "net"
    assert "date complète" in a.facteurs and "lieu" in a.facteurs
    assert a.gramps_id == "I1"


def test_le_lieu_se_compare_a_la_commune_pas_a_la_hierarchie():
    """`EventFact.place` est la hiérarchie complète (« commune, département,
    pays »), `place_name` la commune seule. Le relevé, lui, ne donne qu'une
    commune. Comparer `place` rendrait l'égalité systématiquement fausse sur
    les vraies données : plus aucun facteur « lieu », donc plus aucun `net` en
    production. Ce test échoue si on revient à comparer `place`."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = EventFact(type="Death", dateval=[0, 0, 0, False], modifier=0,
                        place="Saint-Martin-d'Auxigny, Cher, France",
                        place_name="Saint-Martin-d'Auxigny", sortval=0)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "lieu" in a.facteurs


def test_lieu_se_rabat_sur_le_premier_segment_si_place_name_est_vide():
    """`place_name` n'est pas toujours renseigné selon la façon dont la fiche a
    été saisie ; le premier segment de la hiérarchie est alors la commune."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = EventFact(type="Death", dateval=[0, 0, 0, False], modifier=0,
                        place="Saint-Martin-d'Auxigny, Cher, France",
                        place_name="", sortval=0)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "lieu" in a.facteurs


def test_lieu_discordant_n_est_ni_facteur_ni_divergence():
    """Une inégalité de chaîne n'est PAS une contradiction. « Saint Martin
    d'Auxigny » contre « Saint-Martin-d'Auxigny » est une graphie, pas une
    autre commune, et rien ici ne peut trancher — aucun résolveur de lieux
    n'est disponible dans un moteur pur. Vetoer là-dessus écarterait de bons
    candidats ; le veto reste réservé aux dates, entiers non ambigus."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.divergences == []
    assert "lieu" not in a.facteurs
    assert a.verdict == "gris"          # date complète (5) + prénom (1) = 6


def test_divergence_de_date_est_un_veto_pas_un_malus():
    """Un empilement de concordances ne doit jamais écraser une contradiction."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert a.divergences


def test_annee_seule_ne_fait_pas_une_date_complete():
    """dateval [0, 0, 1894] est une année, pas une date : aucun facteur fort."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", annee=1894)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []          # une année n'est pas non plus une divergence


def test_date_texte_n_est_ni_concordance_ni_divergence():
    """modifier==6 : date en texte libre, non comparable terme à terme."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", 10, 12, 1894, modifier=6)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []


def test_facteurs_faibles_seuls_ne_font_jamais_un_net():
    p = _p("I1", "JACQUET", "Rose")          # ni date ni lieu : prénom + année seuls
    p.birth = _ev("Birth", annee=1821, modifier=3)      # 3 = about
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict != "net"


def test_parent_nomme_concordant_pese_lourd():
    """Les DEUX parents du relevé (père et mère) concordent avec ceux de
    l'arbre : c'est le facteur « deux parents nommés », pas « parent nommé »
    — les deux ne coexistent jamais pour un même candidat (voir
    `facteurs_et_divergences`), sous peine de compter la même preuve deux
    fois."""
    p = _p("I1", "JACQUET", "Rose")
    a = apparier(ROSE, [p], {"JACQUET": 0.75},
                 {"hI1": ["Pierre JACQUET", "Marie Anne VILLEPELLET"]})
    assert "deux parents nommés" in a.facteurs
    assert "parent nommé" not in a.facteurs
    assert a.verdict == "net"


def test_un_seul_parent_nomme_ne_suffit_pas_a_lui_seul():
    """Garde-fou : un père homonyme, seul, ne prouve presque rien — un
    patronyme courant peut très bien rattacher deux Pierre JACQUET sans
    aucun lien de parenté réel. Sans ce test, un futur ajustement de poids
    pourrait glisser vers un homonyme isolé suffisant pour écrire un
    verdict `net` dans l'arbre ; ici, seul « parent nommé » (facteur faible
    pris seul, sans date ni lieu) est émis, jamais « deux parents nommés »."""
    p = _p("I1", "JACQUET", "Rose")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {"hI1": ["Pierre JACQUET"]})
    assert "parent nommé" in a.facteurs
    assert "deux parents nommés" not in a.facteurs
    assert a.verdict != "net"


def test_candidats_multiples_a_poids_egal_donnent_gris():
    a1 = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a2 = _mort(_p("I2", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [a1, a2], {"JACQUET": 0.75}, {})
    assert a.verdict == "gris"
    assert sorted(a.candidats) == ["I1", "I2"]
    assert a.gramps_id is None


def test_aucun_candidat_donne_aucun():
    a = apparier(ROSE, [], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert a.candidats == []


def test_patronyme_rare_ajoute_un_facteur_fort():
    p = _mort(_p("I1", "VILLEPELLET", "Marie"), 10, 12, 1894)
    r = _releve(sujet_nom="VILLEPELLET", sujet_prenom="Marie",
                evenement_date="1894-12-10")
    a = apparier(r, [p], {"VILLEPELLET": 0.01}, {})
    assert "patronyme rare" in a.facteurs
