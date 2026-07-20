import json

import httpx
import pytest
from crewai_custom_tools.tools.genealogy.gramps import write_tools
from crewai_custom_tools.tools.genealogy.gramps.client import GrampsClient, GrampsConfig

from genecrew.pistes import Piste, cle_derivee, consigner, evaluer_force, marqueur, marqueurs_existants

CONFIG = GrampsConfig(api_url="http://g.test/api", username="u", password="p")


def test_deux_facteurs_independants_font_une_piste_forte():
    assert evaluer_force(["nom", "date de naissance complète"], []) == "forte"


def test_un_seul_facteur_ne_suffit_pas():
    assert evaluer_force(["nom"], []) == "faible"
    assert evaluer_force([], []) == "faible"


def test_une_divergence_dure_degrade_malgre_les_concordances():
    # Règle du projet : une contradiction irréductible l'emporte sur n'importe
    # quel nombre de concordances.
    assert evaluer_force(["nom", "prénom", "lieu"], ["départements incompatibles"]) == "faible"


def test_cle_derivee_est_stable_entre_appels():
    a = cle_derivee("mdh", ["SOULAT", "Hoche", "1915-05-09", "154e RI"])
    b = cle_derivee("mdh", ["SOULAT", "Hoche", "1915-05-09", "154e RI"])
    assert a == b and len(a) == 8


def test_cle_derivee_normalise_casse_accents_et_espaces():
    # La même fiche rendue différemment doit produire la MÊME clé, sinon
    # l'idempotence saute au premier changement de formatage de la source.
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) == cle_derivee("mdh", ["  soulat ", "HOCHÉ".replace("É", "e")])


def test_cle_derivee_distingue_des_fiches_differentes():
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) != cle_derivee("mdh", ["SOULAT", "Kléber"])


def test_marqueur_natif_et_derive():
    assert marqueur("matchid", "a1b2c3d4") == "[genecrew:piste:matchid:a1b2c3d4]"
    # Le préfixe k= signale une identité dérivée, lisible d'un coup d'œil dans Gramps.
    assert marqueur("mdh", "6f2a91c4", derivee=True) == "[genecrew:piste:mdh:k=6f2a91c4]"


def test_cle_derivee_ne_depend_pas_du_salage_du_processus():
    # hash() est salé à chaque exécution : une clé qui en dépendrait casserait
    # l'idempotence entre deux lancements. On verrouille la valeur attendue.
    assert cle_derivee("mdh", ["SOULAT", "Hoche"]) == cle_derivee("mdh", ["SOULAT", "Hoche"])
    import subprocess
    import sys
    autre = subprocess.run(
        [sys.executable, "-c",
         "from genecrew.pistes import cle_derivee; print(cle_derivee('mdh', ['SOULAT','Hoche']))"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert autre == cle_derivee("mdh", ["SOULAT", "Hoche"])


@pytest.fixture(autouse=True)
def _ecriture_reelle(monkeypatch):
    monkeypatch.setenv("GENECREW_DRY_RUN", "false")


def _client(records, notes=()):
    """Client Gramps mocké. `notes` = corps des notes déjà rattachées à la personne."""
    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/people/" and request.method == "GET":
            return httpx.Response(200, json=[{
                "handle": "h1", "gramps_id": "I1123",
                "note_list": [], "tag_list": [],
                "extended": {"notes": [{"text": {"string": n}} for n in notes]},
            }])
        records.append((request.method, str(request.url.path),
                        json.loads(request.content) if request.content else None))
        if request.method == "POST":
            return httpx.Response(201, json=[{"new": [{"handle": "nouveau"}]}])
        return httpx.Response(200, json={})
    return GrampsClient(CONFIG, transport=httpx.MockTransport(handler))


def _piste(force="forte", **kw):
    base = dict(gramps_id="I1123", handle="h1", source="matchid", identite="a1b2c3d4",
                requete="nom=SOULAT&prenom=Kleber", url="https://deces.matchid.io/id/a1b2c3d4",
                concordances=["nom", "date de naissance complète"], divergences=[], force=force)
    base.update(kw)
    return Piste(**base)


def test_marqueurs_existants_lit_les_notes_de_la_personne():
    client = _client([], notes=["[genecrew:piste:matchid:a1b2c3d4] Piste de décès…",
                                "Note humaine sans marqueur"])
    assert marqueurs_existants(client, "I1123") == {"[genecrew:piste:matchid:a1b2c3d4]"}


def test_une_piste_forte_est_ecrite(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste())
    assert out["ecrite"] is True
    posts = [r for r in records if r[0] == "POST"]
    assert any("/notes/" in r[1] for r in posts), "la note n'a pas été créée"


def test_une_piste_faible_ne_touche_jamais_l_arbre(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste(force="faible"))
    assert out["ecrite"] is False and out["raison"] == "faible"
    assert not [r for r in records if r[0] in ("POST", "PUT")], "une faible a écrit dans l'arbre"


def test_second_passage_n_ecrit_rien(mocker):
    # LE test qui justifie tout le mécanisme de marqueur.
    records = []
    client = _client(records, notes=["[genecrew:piste:matchid:a1b2c3d4] déjà consignée"])
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste())
    assert out["ecrite"] is False and out["raison"] == "déjà consignée"
    assert not [r for r in records if r[0] in ("POST", "PUT")]


def test_dry_run_n_ecrit_rien(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    out = consigner(client, _piste(), dry_run=True)
    assert out["ecrite"] is False and out["raison"] == "simulation"
    assert not [r for r in records if r[0] == "PUT"]


def test_le_corps_de_la_note_dit_l_absence_de_permalien(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    consigner(client, _piste(url=None, identite="6f2a91c4", identite_derivee=True, source="mdh"))
    corps = next(r[2]["text"]["string"] for r in records
                 if r[0] == "POST" and "/notes/" in r[1])
    assert "ABSENT" in corps
    assert "http" not in corps, "aucune URL ne doit apparaître quand la source n'en donne pas"
    assert corps.startswith("[genecrew:piste:mdh:k=6f2a91c4]")


def test_le_corps_ne_conclut_pas(mocker):
    records = []
    client = _client(records)
    mocker.patch.object(write_tools, "get_client", return_value=client)
    consigner(client, _piste())
    corps = next(r[2]["text"]["string"] for r in records
                 if r[0] == "POST" and "/notes/" in r[1])
    assert "Une piste n'est pas un fait" in corps


def test_rapport_separe_fortes_et_faibles():
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([_piste(), _piste(force="faible", identite="zzz")],
                               "2026-07-20", dry_run=False)
    assert "Pistes fortes" in md and "Pistes faibles" in md
    assert "écritures appliquées" in md


def test_rapport_dit_le_mode_simulation():
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([_piste()], "2026-07-20", dry_run=True)
    assert "simulation" in md


def test_rapport_contient_les_faibles_absentes_de_l_arbre():
    # Les faibles n'existent QUE là : si le rapport les perd, elles sont perdues.
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([_piste(force="faible", identite="zzz",
                                       concordances=["nom"])], "2026-07-20", dry_run=False)
    assert "zzz" in md


def test_rapport_sans_piste_le_dit():
    from genecrew.pistes import render_rapport_pistes
    md = render_rapport_pistes([], "2026-07-20", dry_run=False)
    assert "Aucune piste" in md


def test_rapport_suit_le_dry_run_effectif_pas_celui_demande(monkeypatch):
    """L'env impose la simulation : le rapport ne doit pas annoncer des écritures.

    Ce cas était masqué par la fixture autouse `_ecriture_reelle`, qui pose
    GENECREW_DRY_RUN=false pour tout le module : le test du mode passait donc pour
    la mauvaise raison. Ici on rétablit la contrainte d'environnement explicitement.

    Le scénario réel : GENECREW_DRY_RUN absent ou vrai — le défaut sûr du projet —
    et un appelant qui passe dry_run=False. `consigner` répond « simulation » pour
    chaque piste et n'écrit rien, pendant que le rapport annoncerait « écritures
    appliquées ». Le généalogiste croirait avoir des pistes dans Gramps ; il n'en
    aurait aucune, et rien ne le lui dirait au passage suivant.
    """
    from genecrew.pistes import render_rapport_pistes

    monkeypatch.setenv("GENECREW_DRY_RUN", "true")
    md = render_rapport_pistes([_piste()], "2026-07-20", dry_run=False)
    assert "simulation" in md
    assert "écritures appliquées" not in md
