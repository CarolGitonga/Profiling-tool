import os
import networkx as nx
from pyvis.network import Network
import spacy
import re
from django.conf import settings
from profiles.models import RawPost

# ======================================================
# Load spaCy model once
# ======================================================
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    raise RuntimeError("spaCy model 'en_core_web_sm' is missing. Run: python -m spacy download en_core_web_sm")


# ======================================================
# Helper: Extract platform-specific entities
# ======================================================
def extract_entities_from_text(text):
    """Extract NER, hashtags, mentions, capitalized words, TikTok/GitHub patterns."""
    ents = []

    if not text:
        return ents

    doc = nlp(text)

    # Named Entities
    ents.extend([
        ent.text.strip() for ent in doc.ents
        if ent.label_ in {"PERSON", "ORG", "GPE", "PRODUCT"}
    ])

    # Hashtags and mentions
    ents.extend(re.findall(r"#\w+", text))
    ents.extend(re.findall(r"@\w+", text))

    # Capitalized keyword candidates (names, brands)
    ents.extend([
        token.text for token in doc
        if token.text.istitle() and len(token.text) > 2 and not token.is_stop
    ])

    # TikTok style keywords (e.g., sounds, challenges)
    ents.extend(re.findall(r"[A-Za-z0-9]+Challenge", text))
    ents.extend(re.findall(r"[A-Za-z0-9]+Sound", text))

    # GitHub style entities (Repos, orgs)
    ents.extend(re.findall(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text))   # repo names

    # dedupe
    return list(set(ents))


# ======================================================
# Main: generate entity graph
# ======================================================
def generate_entity_graph(username, platform="Twitter"):
    """
    Multi-platform NER / hashtag / mention / keyword graph.
    Set platform="all" to merge all platforms for the user.
    Returns (media_url_path, cluster_summaries)
    """

    # Normalize platform
    platform = platform.capitalize()

    # Query posts
    if platform.lower() == "all":
        posts = RawPost.objects.filter(profile__username=username)
    else:
        posts = RawPost.objects.filter(profile__username=username, profile__platform=platform)

    if not posts.exists():
        print(f"⚠️ No posts found for {username} on {platform}.")
        return None, []

    G = nx.Graph()
    print(f"🧠 Extracting entities for {username} on {platform}...")

    for post in posts:
        if not post.content:
            continue
        
        entities = extract_entities_from_text(post.content)

        # Pairwise co-occurrence edges
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                e1, e2 = entities[i], entities[j]
                if G.has_edge(e1, e2):
                    G[e1][e2]["weight"] += 1
                else:
                    G.add_edge(e1, e2, weight=1)

    if G.number_of_nodes() == 0:
        print(f"⚠️ No meaningful entities extracted for {username}.")
        return None, []

    # ======================================================
    # Cluster Detection
    # ======================================================
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = list(greedy_modularity_communities(G))
    except Exception:
        communities = [set(G.nodes())]

    # Map node → cluster index
    cluster_map = {}
    for i, comm in enumerate(communities):
        for node in comm:
            cluster_map[node] = i

    # ======================================================
    # Visualization
    # ======================================================
    net = Network(
        height="700px",
        width="100%",
        bgcolor="#ffffff",
        font_color="black"
    )
    net.barnes_hut(gravity=-25000, central_gravity=0.3, spring_length=120)
    net.from_nx(G)

    cluster_colors = [
        "#007bff", "#28a745", "#17a2b8", "#ffc107", 
        "#dc3545", "#6f42c1", "#20c997"
    ]

    # Style nodes
    for node in net.nodes:
        node_id = node["id"]
        degree = G.degree(node_id)
        cluster_id = cluster_map.get(node_id, 0)

        if node_id.startswith("#"):
            color = "#007bff"     # Hashtags
        elif node_id.startswith("@"):
            color = "#17a2b8"     # Mentions
        else:
            color = cluster_colors[cluster_id % len(cluster_colors)]

        node["color"] = color
        node["size"] = 15 + degree * 2.5
        node["title"] = f"<b>{node_id}</b><br>Connections: {degree}<br>Cluster: {cluster_id}"

    # Label top nodes
    label_nodes = []
    for comm in communities:
        subgraph = G.subgraph(comm)
        top_nodes = sorted(subgraph.degree, key=lambda x: x[1], reverse=True)[:3]
        label_nodes.extend([n for n, _ in top_nodes])

    for node in net.nodes:
        if node["id"] in label_nodes:
            node["label"] = node["id"]
        else:
            node["label"] = ""

    # ======================================================
    # Generate textual cluster summaries
    # ======================================================
    cluster_summaries = []
    for i, comm in enumerate(communities):
        subgraph = G.subgraph(comm)
        top_nodes = sorted(subgraph.degree, key=lambda x: x[1], reverse=True)[:5]
        top_list = ", ".join([n for n, _ in top_nodes])
        summary = f"Cluster {i+1}: Top entities — {top_list}"
        cluster_summaries.append(summary)

    # ======================================================
    # Save HTML (Render compatible)
    # ======================================================
    output_dir = getattr(settings, "MEDIA_ROOT", "/tmp/media")
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{username}_{platform.lower()}_entity_graph.html"
    output_path = os.path.join(output_dir, filename)

    try:
        net.write_html(output_path, notebook=False, local=False, cdn_resources="remote")
    except TypeError:
        net.write_html(output_path, notebook=False, local=False)

        # Add CDN manually if missing
        with open(output_path, "r", encoding="utf-8") as f:
            html = f.read()

        if "vis-network.min.js" not in html:
            cdn = """
            <script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
            <link href="https://cdn.jsdelivr.net/npm/vis-network@9.1.2/styles/vis-network.min.css" rel="stylesheet">
            """
            html = html.replace("<head>", f"<head>{cdn}")

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)

    print(f"✅ Entity graph saved → {output_path}")

    media_url = getattr(settings, "MEDIA_URL", "/media/")
    return f"{media_url}{filename}", cluster_summaries
