import io
import base64
from wordcloud import WordCloud
import matplotlib.pyplot as plt

def generate_wordcloud(text: str):
    """
    Generate a word cloud image from text and return it as base64 string for HTML embedding.
    """
    # Create wordcloud
    wc = WordCloud(
        width=600, height=400,
        background_color="white",
        colormap="viridis",
        max_words=100
    ).generate(text)

    # Convert to PNG in memory
    buffer = io.BytesIO()
    plt.figure(figsize=(6, 4))
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(buffer, format="png")
    plt.close()
    buffer.seek(0)

    # Encode as base64 for embedding
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
