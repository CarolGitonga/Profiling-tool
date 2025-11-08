import os
import networkx as nx
from pyvis.network import Network
import spacy
from django.conf import settings
from profiles.models import RawPost

# Load spaCy model globally (only once)
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise RuntimeError("⚠️ spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")

def generate_entity_graph(username, platform="Twitter"):
    """
    Generate an interactive entity co-occurrence graph for a user's posts.
    Returns the relative path to the generated HTML file (for embedding or linking).
    """
    posts = RawPost.objects.filter(profile__username=username, profile__platform=platform)
    if not posts.exists():
        print(f"⚠️ No posts found for {username} on {platform}.")
        return None

    # Initialize graph
    G = nx.Graph()
    print(f"🧠 Extracting entities for {username}...")

    for post in posts:
        if not post.content:
            continue

        # Extract entities (Named Entities + Hashtags)
        doc = nlp(post.content)
        entities = [ent.text for ent in doc.ents if ent.label_ in {"PERSON", "ORG", "GPE", "PRODUCT"}]
        hashtags = [word for word in post.content.split() if word.startswith("#")]
        all_entities = list(set(entities + hashtags))

        # Connect entities that co-occur in same post
        for i in range(len(all_entities)):
            for j in range(i + 1, len(all_entities)):
                e1, e2 = all_entities[i], all_entities[j]
                if G.has_edge(e1, e2):
                    G[e1][e2]["weight"] += 1
                else:
                    G.add_edge(e1, e2, weight=1)

    if len(G.nodes) == 0:
        print(f"⚠️ No named entities or hashtags found for {username}.")
        return None

    # --- Build the interactive PyVis graph ---
    net = Network(height="700px", width="100%", bgcolor="#ffffff", font_color="black", directed=False)
    net.barnes_hut(gravity=-25000, central_gravity=0.3, spring_length=120)
    net.from_nx(G)

    # Style nodes: hashtags = blue, entities = green
    for node in net.nodes:
        degree = G.degree(node["id"])
        node["size"] = 15 + degree * 2.5
        node["color"] = "#007bff" if node["id"].startswith("#") else "#28a745"
        node["title"] = f"{node['id']}<br>Connections: {degree}"

    # --- Save HTML file ---
    output_dir = os.path.join(settings.MEDIA_ROOT)
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{username}_entity_graph.html"
    output_path = os.path.join(output_dir, filename)
    net.write_html(output_path, notebook=False, local=True)

    print(f"✅ Entity graph written to {output_path}")

    # Return relative URL path (for embedding or linking)
    return os.path.join(settings.MEDIA_URL, filename)
