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


def _ev(type_, jour=0, mois=0, annee=0, lieu="", modifier=0, dateval=None,
        quality=0):
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
                     year=annee or None, modifier=modifier, quality=quality,
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


def test_veto_resiste_a_un_empilement_qui_depasse_le_seuil():
    """Le test voisin n'oppose au veto que 4 points, la moitié de `SEUIL_NET` :
    il passerait encore si le veto n'était qu'un malus, ou même s'il
    disparaissait. Ici les concordances pèsent 12 — deux parents nommés (8) +
    lieu (3) + prénom (1) —, largement de quoi faire un `net`, et une seule
    date qui diverge doit tout de même tout annuler."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75},
                 {"hI1": ["Pierre JACQUET", "Marie Anne VILLEPELLET"]})
    assert a.verdict == "aucun"
    assert a.divergences


def test_releve_de_mariage_ne_se_compare_a_aucun_evenement():
    """« Marriage » est une valeur documentée d'`evenement_type`, mais le
    mariage vit sur la FAMILLE, pas sur la personne : `PersonFacts` n'en porte
    aucune trace. Un `else` qui rendait la naissance faisait comparer un relevé
    de mariage à un acte de naissance — et né et marié dans la même commune est
    le cas ORDINAIRE, donc on tirait un facteur fort « lieu » d'une comparaison
    qui n'avait jamais regardé le mariage."""
    p = _p("I1", "JACQUET", "Rose")
    p.birth = _ev("Birth", 10, 12, 1894, "Saint-Martin-d'Auxigny")
    r = _releve(evenement_type="Marriage", evenement_date="1894-12-10",
                evenement_lieu="Saint-Martin-d'Auxigny")
    a = apparier(r, [p], {"JACQUET": 0.75}, {})
    assert "lieu" not in a.facteurs
    assert "date complète" not in a.facteurs
    assert a.divergences == []


def test_verdict_aucun_dit_de_qui_il_parle():
    """Un `aucun` doit rester relisible : sans le `gramps_id` en préfixe, une
    liste de divergences issue de plusieurs candidats ne dit pas laquelle vient
    de qui, et le relecteur ne peut pas remonter à la fiche."""
    a1 = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901)
    a2 = _mort(_p("I2", "JACQUET", "Rose"), 5, 6, 1902)
    a = apparier(ROSE, [a1, a2], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert any(d.startswith("I1 : ") for d in a.divergences)
    assert any(d.startswith("I2 : ") for d in a.divergences)


def test_verdict_aucun_sur_un_seul_candidat_garde_ses_facteurs():
    """Quand un seul candidat a été écarté, il n'y a aucune ambiguïté sur QUI
    a été vu : remonter son identité et ce qui concordait chez lui évite au
    relecteur de refaire l'analyse à la main pour comprendre le rejet."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert a.gramps_id == "I1"
    assert "lieu" in a.facteurs and "prénom" in a.facteurs


def test_annee_seule_ne_fait_ni_facteur_ni_divergence():
    """dateval [0, 0, 1901] est une année, pas une date : aucun facteur fort.

    Deux précautions dans le montage. L'année de l'arbre est DISCORDANTE avec
    celle du relevé (1894) : avec la même année on ne saurait pas distinguer
    « jamais comparé » de « comparé et concordant ». Et le candidat reste
    ÉLIGIBLE grâce au lieu — sur un candidat rejeté sans facteur, `facteurs`
    serait vide de toute façon et l'assertion ne pourrait pas échouer."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", annee=1901, lieu="Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict != "aucun"         # l'assertion porte sur une liste peuplée
    assert "lieu" in a.facteurs
    assert "date complète" not in a.facteurs
    assert a.divergences == []          # une année n'est pas non plus une divergence


def test_candidat_sans_aucun_facteur_donne_aucun():
    """Porte d'entrée du moteur, jamais verrouillée jusqu'ici : un homonyme de
    patronyme et rien d'autre — prénom différent, aucun événement, aucun parent
    connu, patronyme courant. Rien ne concorde, donc rien ne doit sortir."""
    p = _p("I1", "JACQUET", "Jean")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"
    assert a.facteurs == []
    assert a.divergences == []


def test_date_texte_n_est_ni_concordance_ni_divergence():
    """modifier==6 : date en texte libre, non comparable terme à terme."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", 10, 12, 1894, modifier=6)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []


def test_date_approximative_n_est_pas_une_date_complete():
    """modifier==3 (« vers le 10 décembre 1894 ») : la source ne s'engage pas
    sur le jour. En tirer le facteur FORT « date complète » (5 points)
    affirmerait une précision que le document ne donne pas — et c'est
    exactement ce qui inscrirait une fausseté dans l'arbre."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    p.death.modifier = 3
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []
    assert "lieu" in a.facteurs         # le candidat reste éligible


def test_date_approximative_divergente_n_est_pas_un_veto():
    """Symétrique du test précédent : une date approximative qui diffère ne
    peut pas non plus contredire, sans quoi un « vers 1901 » écarterait un bon
    candidat sur une précision que la source n'a jamais affirmée."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901, "Saint-Martin-d'Auxigny")
    p.death.modifier = 3
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.divergences == []
    assert a.verdict != "aucun"


def test_intervalle_de_dates_n_est_pas_une_date_complete():
    """Pour un intervalle (modifier 4) ou une durée (5), Gramps met DEUX dates
    dans `dateval` : huit éléments. Le garde `len(dateval) < 3` passe et les
    trois premières composantes se lisent comme une date exacte — on
    affirmerait « le 10/12/1894 » là où la source dit « entre le 10/12/1894 et
    le 02/03/1901 »."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", lieu="Saint-Martin-d'Auxigny", modifier=4,
                  dateval=[10, 12, 1894, False, 2, 3, 1901, False])
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert a.divergences == []
    assert "lieu" in a.facteurs


def test_date_calculee_n_est_pas_une_date_complete():
    """`quality==2` (calculée) : la date n'a pas été lue dans un acte, elle a été
    RECONSTRUITE — typiquement une naissance déduite d'un « Âge : 73 ans » au
    décès, ce que porte précisément le relevé de référence de ce projet.

    Le piège est que `quality` est ORTHOGONAL à `modifier` : une date calculée
    porte `modifier == 0` (elle n'est ni « vers », ni « avant », ni un
    intervalle) ET un `dateval` complet. Elle traverse donc intégralement le
    garde sur `modifier` et produirait le facteur FORT « date complète » (5
    points) sur une date qu'aucune source n'a jamais affirmée."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    p.death.quality = 2
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "date complète" not in a.facteurs
    assert "lieu" in a.facteurs          # le candidat reste éligible


def test_date_calculee_divergente_n_est_pas_un_veto():
    """Symétrique du précédent, et c'est le sens le plus grave des deux : une
    date reconstruite qui diffère du relevé produirait une DIVERGENCE, donc un
    veto — et un candidat vetoé ne revient jamais devant le relecteur humain.
    Un arrondi d'âge au décès suffirait à faire disparaître silencieusement la
    bonne personne."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 2, 3, 1901, "Saint-Martin-d'Auxigny")
    p.death.quality = 2
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.divergences == []
    assert a.verdict != "aucun"


def test_annee_approximative_exige_une_date_exacte_ou_about():
    """« avant 1821 » (modifier 1) n'est pas une année comparable à ±2 : la
    source ne dit pas quelle année, elle dit une borne."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", lieu="Saint-Martin-d'Auxigny")
    p.birth = _ev("Birth", annee=1821, modifier=1)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "année approximative" not in a.facteurs
    assert "lieu" in a.facteurs         # le candidat reste éligible


def test_annee_about_reste_une_annee_approximative():
    """modifier==3 (« vers 1821 ») est précisément ce que le facteur FAIBLE
    « année approximative » est fait pour accueillir — il ne doit pas être
    écarté avec les bornes et les intervalles."""
    p = _p("I1", "JACQUET", "Rose")
    p.death = _ev("Death", lieu="Saint-Martin-d'Auxigny")
    p.birth = _ev("Birth", annee=1821, modifier=3)
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert "année approximative" in a.facteurs


def test_facteurs_faibles_seuls_ne_font_jamais_un_net():
    """`assert verdict != "net"` ne verrouillait rien : sur 2 points, supprimer
    la garde `FACTEURS_FORTS` donnerait `gris` (2 < SEUIL_NET) et le test
    passerait toujours. Seule la garde produit `aucun` ici — c'est donc elle
    que cette assertion-là teste vraiment."""
    p = _p("I1", "JACQUET", "Rose")          # ni date ni lieu : prénom + année seuls
    p.birth = _ev("Birth", annee=1821, modifier=3)      # 3 = about
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    assert a.verdict == "aucun"


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


def test_candidats_a_poids_proches_donnent_gris_pas_un_gagnant():
    """La spec dit « poids COMPARABLES », pas « poids égaux ». Deux personnes
    partageant date ET lieu de décès — exactement ce que ce projet cherche par
    ailleurs sous le nom de doublons — donnent 9 et 8 dès que l'une des deux a
    son prénom orthographié autrement. Départager sur l'égalité exacte élirait
    la première, donc écrirait dans l'arbre, sur la foi d'UN point de prénom,
    entre deux personnes appuyées par la même preuve. Pire : la branche `net`
    ne renvoyait que le gagnant, si bien que le relecteur humain n'aurait
    jamais su qu'il y avait un concurrent à un point."""
    a1 = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a2 = _mort(_p("I2", "JACQUET", "Roze"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [a1, a2], {"JACQUET": 0.75}, {})
    assert a.poids == 9 and a.verdict == "gris"
    assert sorted(a.candidats) == ["I1", "I2"]
    assert a.gramps_id is None


def test_concurrent_retenu_juste_au_dela_de_la_marge_laisse_le_gagnant_seul():
    """Borne HAUTE de `MARGE_EX_AEQUO`, et correction d'un test qui ne testait
    rien.

    La version précédente opposait au gagnant un concurrent sans le moindre
    facteur fort (prénom seul) : `_verdict_candidat` lui rendait « aucun » et le
    filtre `retenus` l'éliminait AVANT que `ex_aequo` ne soit calculé. Le test
    passait donc quelle que soit la valeur de la constante — vérifié : il
    passait encore avec `MARGE_EX_AEQUO = 1000`. C'est le défaut exact de
    l'assertion qui ne peut pas échouer sur la garde qu'elle prétend protéger.

    Ici le concurrent est RÉELLEMENT retenu : il porte le facteur fort « date
    complète » et n'a aucune divergence (son lieu discordant n'en produit pas).
    Il pèse 5 contre 9, soit un écart de 4, juste AU-DELÀ de la marge — le
    gagnant doit donc sortir seul. Ce test tombe si la marge monte à 4."""
    a1 = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a2 = _mort(_p("I2", "JACQUET", "Roze"), 10, 12, 1894, "Sancerre")
    a = apparier(ROSE, [a1, a2], {"JACQUET": 0.75}, {})
    assert a.verdict == "net"
    assert a.poids == 9                 # date (5) + lieu (3) + prénom (1)
    assert a.gramps_id == "I1"
    assert a.candidats == ["I1"]


def test_concurrent_retenu_juste_en_deca_de_la_marge_donne_gris():
    """Borne BASSE de `MARGE_EX_AEQUO`, et le scénario qui l'a fixée à 3.

    I1 et I2 partagent la même date de décès COMPLÈTE — la signature d'un
    doublon d'arbre. 9 contre 6 : le seul différenciateur est le facteur
    « lieu », c'est-à-dire, hors `lieux_resolus`, une simple égalité de chaîne
    dont ce même moteur établit par ailleurs qu'elle ne prouve rien (« une
    inégalité de chaîne n'est PAS une contradiction »). Il suffit que I2 ait sa
    commune saisie autrement pour perdre ses 3 points, et une écriture
    automatique se retrouverait arbitrée par une graphie.

    Écart de 3, donc EN DEÇÀ de la marge : verdict gris, les deux candidats
    listés. Ce test tombe si la marge redescend à 2. Avec celui qui le précède,
    il encadre la valeur — aucune autre ne les fait passer tous les deux."""
    a1 = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a2 = _mort(_p("I2", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    a = apparier(ROSE, [a1, a2], {"JACQUET": 0.75}, {})
    assert a.verdict == "gris"
    assert a.poids == 9                 # le meilleur des deux, mais pas élu
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


# --- Lieux résolus en identifiant canonique --------------------------------
#
# Le moteur reste PUR : il ne résout rien lui-même, il reçoit de l'orchestration
# un dictionnaire « lieu brut normalisé → identifiant canonique de commune ».
# Cet identifiant est un code NATIONAL préfixé par le pays (« FR:18209»,
# « CH:2701 », « DE:06531000 ») — jamais un code nu. Un code INSEE français et
# un numéro OFS suisse peuvent partager la même chaîne numérique sans désigner
# la même commune ; le préfixe pays est ce qui lève cette ambiguïté. C'est ce
# qui rétablit un veto SÛR sur les lieux : deux identifiants distincts sont
# démontrablement deux communes différentes, là où deux chaînes différentes
# peuvent n'être qu'une graphie.

def test_deux_identifiants_canoniques_egaux_donnent_le_facteur_lieu():
    """Les deux graphies diffèrent (tirets contre espaces) : sans résolution, le
    repli sur la chaîne ne donnerait AUCUN facteur. C'est donc bien
    l'identifiant canonique qui produit le facteur ici, et rien d'autre."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint Martin d'Auxigny")
    resolus = {"SAINT MARTIN D'AUXIGNY": "FR:18197",
               "SAINT-MARTIN-D'AUXIGNY": "FR:18197"}
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {}, lieux_resolus=resolus)
    assert "lieu" in a.facteurs
    assert a.divergences == []


def test_deux_identifiants_canoniques_differents_vetoent_meme_un_candidat_lourd():
    """Le point du veto : deux communes DÉMONTRÉES distinctes annulent tout, y
    compris un candidat qui pèse largement au-dessus de `SEUIL_NET` — deux
    parents nommés (8) + prénom (1). Si la divergence n'était qu'un malus, ce
    candidat sortirait encore `net`."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    resolus = {"SANCERRE": "FR:18241", "SAINT-MARTIN-D'AUXIGNY": "FR:18197"}
    r = _releve(evenement_lieu="Saint-Martin-d'Auxigny",
                personnes_liees=ROSE.personnes_liees)
    a = apparier(r, [p], {"JACQUET": 0.75},
                 {"hI1": ["Pierre JACQUET", "Marie Anne VILLEPELLET"]},
                 lieux_resolus=resolus)
    assert a.verdict == "aucun"
    assert a.divergences
    assert "lieu" not in a.facteurs


def test_meme_numero_national_deux_pays_differents_est_une_divergence():
    """Le défaut qu'on corrige ici, verrouillé : un code INSEE français et un
    numéro OFS suisse peuvent partager la même chaîne de chiffres sans désigner
    la même commune. Deux identifiants qui ne partagent que le numéro, pas le
    préfixe pays, DOIVENT diverger — jamais produire le facteur « lieu ». Sans
    ce test, une implémentation qui comparerait les numéros après avoir dépouillé
    le préfixe (un « nettoyage » a priori inoffensif) fabriquerait exactement la
    fausse concordance que ce correctif élimine."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    resolus = {"SANCERRE": "CH:18209", "SAINT-MARTIN-D'AUXIGNY": "FR:18209"}
    r = _releve(evenement_lieu="Saint-Martin-d'Auxigny",
                personnes_liees=ROSE.personnes_liees)
    a = apparier(r, [p], {"JACQUET": 0.75},
                 {"hI1": ["Pierre JACQUET", "Marie Anne VILLEPELLET"]},
                 lieux_resolus=resolus)
    assert a.verdict == "aucun"
    assert a.divergences
    assert "lieu" not in a.facteurs


def test_identifiant_sans_prefixe_pays_est_traite_comme_non_resolu():
    """Garde-fou structurel : une valeur SANS préfixe pays (pas de `:`) ne
    respecte pas le contrat, donc elle est IGNORÉE — le lieu retombe au statut
    non résolu et la comparaison se réplie sur l'égalité de chaîne, jamais sur
    un veto. Le repli est sûr (il ne produit jamais de veto) ; faire confiance à
    un code nu ne l'est pas, puisque c'est exactement le défaut corrigé ici
    (deux codes nationaux de pays différents peuvent coïncider). Ici le côté
    « Sancerre » porte un code nu qui, sans le garde-fou, entrerait en
    comparaison avec le code préfixé du relevé et produirait une divergence —
    ce test tombe si le garde-fou est retiré."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    resolus = {"SANCERRE": "18241", "SAINT-MARTIN-D'AUXIGNY": "FR:18197"}
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {}, lieux_resolus=resolus)
    assert a.divergences == []
    assert "lieu" not in a.facteurs         # chaînes "Sancerre" ≠ "Saint-Martin-d'Auxigny"
    assert a.verdict == "gris"              # date complète (5) + prénom (1) = 6


def test_un_seul_lieu_resolu_retombe_sur_la_chaine_sans_veto():
    """Le lieu du relevé est résolu, celui de l'arbre ne l'est pas : il n'y a
    aucune mesure comparable, donc pas de veto possible. Absent de la mesure ne
    veut pas dire contredit."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {},
                 lieux_resolus={"SAINT-MARTIN-D'AUXIGNY": "FR:18197"})
    assert a.divergences == []
    assert "lieu" not in a.facteurs
    assert a.verdict == "gris"          # date complète (5) + prénom (1) = 6


def test_un_seul_lieu_resolu_accorde_le_facteur_si_les_chaines_concordent():
    """Symétrique du précédent : le repli sur la chaîne reste ACTIF quand un seul
    des deux côtés est résolu. Sans ce test, un repli qui ne rendrait jamais de
    facteur passerait inaperçu."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {},
                 lieux_resolus={"SAINT-MARTIN-D'AUXIGNY": "FR:18197"})
    assert "lieu" in a.facteurs
    assert a.divergences == []


def test_aucun_lieu_resolu_chaines_differentes_ne_veto_pas():
    """Non-régression du comportement acquis : sans résolution, une inégalité de
    chaîne n'est ni facteur ni divergence."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Sancerre")
    a = apparier(ROSE, [p], {"JACQUET": 0.75}, {},
                 lieux_resolus={"BOURGES": "FR:18033"})
    assert a.divergences == []
    assert "lieu" not in a.facteurs


def test_lieux_resolus_vide_ou_absent_ne_change_rien():
    """Rétrocompatibilité stricte : le paramètre est optionnel, et un dictionnaire
    vide doit produire exactement le verdict d'avant."""
    p = _mort(_p("I1", "JACQUET", "Rose"), 10, 12, 1894, "Saint-Martin-d'Auxigny")
    sans = apparier(ROSE, [p], {"JACQUET": 0.75}, {})
    vide = apparier(ROSE, [p], {"JACQUET": 0.75}, {}, lieux_resolus={})
    assert sans.model_dump() == vide.model_dump()
    assert sans.verdict == "net" and "lieu" in sans.facteurs
