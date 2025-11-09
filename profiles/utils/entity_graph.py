import os
import networkx as nx
from pyvis.network import Network
import spacy
from django.conf import settings
from profiles.models import RawPost

# ======================================================
# Load spaCy model once globally
# ======================================================
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise RuntimeError("⚠️ spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")

# ======================================================
# Generate Entity Graph (NER + hashtags + mentions + caps)
# ======================================================
def generate_entity_graph(username, platform="Twitter"):
    """
    Generate an interactive entity co-occurrence graph for a user's posts.
    Returns the MEDIA URL path to the generated HTML file.
    """
    posts = RawPost.objects.filter(profile__username=username, profile__platform=platform)
    if not posts.exists():
        print(f"⚠️ No posts found for {username} on {platform}.")
        return None

    G = nx.Graph()
    print(f"🧠 Extracting entities for {username}...")

    for post in posts:
        if not post.content:
            continue

        text = post.content
        doc = nlp(text)

        # --- Named entities (PERSON, ORG, GPE, PRODUCT)
        ents = [ent.text.strip() for ent in doc.ents if ent.label_ in {"PERSON", "ORG", "GPE", "PRODUCT"}]

        # --- Hashtags and mentions
        hashtags = [w for w in text.split() if w.startswith("#")]
        mentions = [w for w in text.split() if w.startswith("@")]

        # --- Capitalized words (possible names)
        caps = [t.text for t in doc if t.text.istitle() and len(t.text) > 2 and not t.is_stop]

        # Combine all and deduplicate
        all_entities = list(set(ents + hashtags + mentions + caps))

        # Create connections between all co-occurring entities
        for i in range(len(all_entities)):
            for j in range(i + 1, len(all_entities)):
                e1, e2 = all_entities[i], all_entities[j]
                if G.has_edge(e1, e2):
                    G[e1][e2]["weight"] += 1
                else:
                    G.add_edge(e1, e2, weight=1)

    if len(G.nodes) == 0:
        print(f"⚠️ No entities or hashtags found for {username}.")
        return None

    # ======================================================
    # 🎨 Visualize with PyVis
    # ======================================================
    net = Network(height="700px", width="100%", bgcolor="#ffffff", font_color="black", directed=False)
    net.barnes_hut(gravity=-25000, central_gravity=0.3, spring_length=120)
    net.from_nx(G)

    for node in net.nodes:
        degree = G.degree(node["id"])
        node["size"] = 15 + degree * 2.5
        if node["id"].startswith("#"):
            node["color"] = "#007bff"  # hashtags = blue
        elif node["id"].startswith("@"):
            node["color"] = "#17a2b8"  # mentions = cyan
        else:
            node["color"] = "#28a745"  # entities/capitalized words = green
        node["title"] = f"{node['id']}<br>Connections: {degree}"

    # ======================================================
    # 💾 Safe file output (Render-compatible)
    # ======================================================
    output_dir = getattr(settings, "MEDIA_ROOT", None) or os.path.join("/tmp", "media")
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{username}_entity_graph.html"
    output_path = os.path.join(output_dir, filename)

    # ✅ Use remote CDN for Render compatibility
    net.write_html(output_path, notebook=False, local=False, cdn_resources="remote")

    print(f"✅ Entity graph written to {output_path}")

    # Return a usable MEDIA URL path
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    return os.path.join(media_url.strip("/"), filename)
