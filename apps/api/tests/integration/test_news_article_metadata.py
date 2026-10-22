from disaster_monitor.infrastructure.media.news_article_parser import _article_metadata

URL = "https://news.example/story"


def test_missing_image_metadata_does_not_use_the_article_page_as_an_image():
    assert _article_metadata('<meta property="og:title" content="Flood">', URL) is None


def test_lazy_figure_retains_its_own_caption_and_credit():
    result = _article_metadata(
        (
            '<meta property="og:title" content="Flood"><figure><img '
            'src="data:image/gif;base64,AA" '
            'data-src="/flood.jpg"><figcaption>Flood in River Town. '
            "Photo: Local Agency</figcaption></figure>"
        ),
        URL,
    )
    assert result is not None
    assert result.image_url == "https://news.example/flood.jpg"
    assert result.credit == "Local Agency"


def test_og_image_does_not_borrow_credit_from_an_unrelated_figure():
    result = _article_metadata(
        (
            '<meta property="og:image" content="/lead.jpg"><figure><img '
            'src="/other.jpg"><figcaption>Photo: Unrelated '
            "Photographer</figcaption></figure>"
        ),
        URL,
    )
    assert result is not None
    assert result.credit is None


def test_repeated_responsive_captions_do_not_pollute_the_photographer_credit():
    caption = "Storm damage in Harbor Town. Photograph: Alex Doe/Local Agency"
    result = _article_metadata(
        '<article><figure><img src="/damage.jpg">'
        f"<figcaption>{caption}</figcaption>"
        f'<figcaption class="expanded-caption">{caption}</figcaption>'
        "</figure></article>",
        URL,
    )
    assert result is not None
    assert result.caption == caption
    assert result.credit == "Alex Doe/Local Agency"


def test_distinct_captions_in_one_figure_preserve_their_qualifications():
    result = _article_metadata(
        '<article><figure><img src="/damage.jpg">'
        "<figcaption>Storm damage in Harbor Town.</figcaption>"
        "<figcaption>Location supplied by the publisher; "
        "capture date unknown.</figcaption>"
        "</figure></article>",
        URL,
    )
    assert result is not None
    assert "Storm damage in Harbor Town." in result.caption
    assert "capture date unknown." in result.caption
