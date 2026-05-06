from app.utils.dream_summary import collect_research_topics, format_latest_sleep_summary


def test_collect_research_topics_dedupes_first_seen_valid_research():
    items = [
        {
            "research": [
                {"research_topic": "Topic A", "research_summary": "Summary A"},
                {"research_topic": "Topic B", "research_summary": "Summary B"},
            ]
        },
        {
            "research": [
                {"research_topic": "topic a", "research_summary": "Duplicate summary"},
                {"research_topic": "Topic C", "research_summary": ""},
            ]
        },
    ]

    assert collect_research_topics(items) == ["Topic A", "Topic B"]


def test_format_latest_sleep_summary_appends_research_block():
    text = format_latest_sleep_summary(
        "Project summary.",
        [
            {
                "research": [
                    {"research_topic": "What memory architecture best supports long-term useful recall?", "research_summary": "x"},
                    {"research_topic": "How should memory evolve over time?", "research_summary": "y"},
                ]
            }
        ],
    )

    assert text == (
        "Project summary.\n\n"
        "[RESEARCH]\n"
        "Topic: What memory architecture best supports long-term useful recall?\n\n"
        "Topic: How should memory evolve over time?\n"
    )


def test_format_latest_sleep_summary_omits_empty_research_block():
    assert format_latest_sleep_summary("Project summary.", [{"research": []}]) == "Project summary."
