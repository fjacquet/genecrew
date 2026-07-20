from crewai_custom_tools.tools.genealogy.models.domain import EventFact, PersonFacts
from crewai_custom_tools.tools.genealogy.pistes import pistes_matchid


def _personne(**kw):
    # PersonFacts exige name et sex ; EventFact exige type et n'a PAS de champ `iso` —
    # la date ISO se dérive de `dateval` via event_iso() (deces.py). dateval = [jour, mois, année, ...]
    base = dict(gramps_id="I1123", handle="h1", name="Kléber SOULAT", sex="M",
                given="Kléber", surname="SOULAT",
                birth=EventFact(type="Birth", year=1888, dateval=[5, 7, 1888, False]),
                death=None)
    base.update(kw)
    return PersonFacts(**base)


_MATCH = {"id": "a1b2c3d4", "name": {"last": "Soulat", "first": ["Kleber"]},
          "birth": {"date": "18880705"}, "death": {"date": "19140926"}}


def test_nom_et_date_complete_font_une_piste_forte():
    p = pistes_matchid(_personne(), _MATCH, "https://deces.matchid.io/id/a1b2c3d4")
    assert p.force == "forte"
    assert p.source == "matchid" and p.identite == "a1b2c3d4"
    assert p.identite_derivee is False
    assert p.url == "https://deces.matchid.io/id/a1b2c3d4"
    assert "nom=" in p.requete or "SOULAT" in p.requete


def test_annee_seule_ne_fait_pas_une_piste_forte():
    # Règle du projet : l'année seule n'est jamais discriminante. Une naissance
    # sans jour ni mois ne fournit qu'UN facteur avec le nom.
    # dateval vide -> event_iso() rend "1888" (année seule), pas une date complète.
    sans_jour = _personne(birth=EventFact(type="Birth", year=1888, dateval=[]))
    maigre = {"id": "x", "name": {"last": "Soulat", "first": ["Kleber"]},
              "birth": {"date": "1888"}, "death": {"date": "19140926"}}
    p = pistes_matchid(sans_jour, maigre, "https://deces.matchid.io/id/x")
    assert p.force == "faible"
    assert "année" in " ".join(p.concordances + p.divergences).lower() or p.concordances == ["nom"]
