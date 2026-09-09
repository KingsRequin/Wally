"""La route publique des cartes du TCG."""


def test_la_route_rend_les_cartes_dans_l_ordre_du_registre(overlay_client):
    r = overlay_client.get("/api/public/tcg/cartes")
    assert r.status_code == 200
    cartes = r.json()["cartes"]
    assert [c["nom"] for c in cartes] == [
        "AZRAËL", "CLAKER", "RHAE", "LILITH", "KINGSREQUIN"]


def test_la_route_ne_fuit_aucune_cle_interne(overlay_client):
    """Elle est PUBLIQUE : tout ce qu'elle rend part à n'importe quel visiteur.
    Les alias, en particulier, n'ont aucune raison d'en sortir."""
    autorisees = {
        "cle", "nom", "legende", "classe", "ultime", "description", "ambiance",
        "cout", "atk", "pv", "aura", "accent", "hero", "fond", "avantPlan",
        "hero3d", "heroCote", "heroHaut", "heroEchelle", "hero3dCote",
        "hero3dHaut", "avantPlanLargeur", "avantPlanBas", "particules",
        "parallaxe", "intensite", "holographique", "holoZone", "bulles",
        "rarete",
    }
    for carte in overlay_client.get("/api/public/tcg/cartes").json()["cartes"]:
        assert set(carte) <= autorisees, set(carte) - autorisees
        assert "alias" not in carte


def test_les_illustrations_sont_versionnees(overlay_client):
    """Sans `?v=<empreinte>`, la zone Cloudflare (`browser_cache_ttl = 14400`)
    fige une illustration retouchée quatre heures chez chaque visiteur."""
    cartes = overlay_client.get("/api/public/tcg/cartes").json()["cartes"]
    azrael = next(c for c in cartes if c["cle"] == "azrael")
    assert azrael["hero"].startswith("/assets/tcg-azrael-hero?v=")
    assert azrael["fond"].startswith("/assets/tcg-azrael-fond?v=")


def test_les_cles_camelcase_correspondent_au_vocabulaire_du_composant(overlay_client):
    """Le composant lit déjà `heroCote`, `avantPlanBas`… Renommer côté JS
    ferait toucher le rendu pendant un refactor dont le critère est « rien ne
    change à l'écran »."""
    cartes = overlay_client.get("/api/public/tcg/cartes").json()["cartes"]
    claker = next(c for c in cartes if c["cle"] == "claker")
    assert claker["avantPlanLargeur"] == "100%"
    assert claker["heroCote"] == "5%"
    rhae = next(c for c in cartes if c["cle"] == "rhae")
    assert rhae["hero3dCote"] == "-26%"


def test_une_carte_sans_avant_plan_le_dit_par_None(overlay_client):
    """`null` et non une chaîne vide : le front teste la présence, et `""` est
    faux en JavaScript mais n'est pas la même chose qu'« absent »."""
    cartes = overlay_client.get("/api/public/tcg/cartes").json()["cartes"]
    azrael = next(c for c in cartes if c["cle"] == "azrael")
    assert azrael["avantPlan"] is None
    assert azrael["hero3d"] is None
