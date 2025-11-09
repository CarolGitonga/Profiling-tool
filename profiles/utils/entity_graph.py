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

        # Combine and deduplicate
        all_entities = list(set(ents + hashtags + mentions + caps))

        # Create co-occurrence edges
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
    # Detect clusters (communities)
    try:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = list(greedy_modularity_communities(G))
    except Exception:
        communities = [set(G.nodes())]
    # Assign cluster index to each node
    cluster_map = {}
    for i, comm in enumerate(communities):
        for node in comm:
            cluster_map[node] = i
    # ======================================================
    # 🎨 Visualize with PyVis
    # ======================================================
    net = Network(height="700px", width="100%", bgcolor="#ffffff", font_color="black", directed=False)
    net.barnes_hut(gravity=-25000, central_gravity=0.3, spring_length=120)
    net.from_nx(G)

    # Node styling by type
    cluster_colors = [
        "#007bff", "#28a745", "#17a2b8", "#ffc107", "#dc3545", "#6f42c1", "#20c997"
    ]

    for node in net.nodes:
        node_id = node["id"]
        degree = G.degree(node_id)
        cluster_id = cluster_map.get(node_id, 0)

        # Color logic
        if node_id.startswith("#"):
            color = "#007bff"  # hashtag
        elif node_id.startswith("@"):
            color = "#17a2b8"  # mention
        else:
            color = cluster_colors[cluster_id % len(cluster_colors)]
        node["color"] = color
        node["size"] = 15 + degree * 2.5
        node["title"] = f"<b>{node_id}</b><br>Connections: {degree}<br>Cluster: {cluster_id}"
    # Add labels for top nodes per cluster
    label_nodes = []
    for i, comm in enumerate(communities):
        # pick top 3 nodes by degree in cluster
        subgraph = G.subgraph(comm)
        top_nodes = sorted(subgraph.degree, key=lambda x: x[1], reverse=True)[:3]
        label_nodes.extend([n for n, _ in top_nodes])
    for node in net.nodes:
        node_id = node["id"]
        node["label"] = node_id if node_id in label_nodes else ""

    # ======================================================
    # 💾 Safe file output (Render-compatible)
    # ======================================================
    output_dir = getattr(settings, "MEDIA_ROOT", None) or os.path.join("/tmp", "media")
    os.makedirs(output_dir, exist_ok=True)

    filename = f"{username}_entity_graph.html"
    output_path = os.path.join(output_dir, filename)

    # --- Try writing with new PyVis arg, fallback if unsupported ---
    try:
        net.write_html(output_path, notebook=False, local=False, cdn_resources="remote")
    except TypeError:
        net.write_html(output_path, notebook=False, local=False)
        # Inject remote vis-network CDN manually
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

    print(f"✅ Entity graph written to {output_path}")

    # Return a usable MEDIA URL path
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    return f"{media_url}{filename}"
