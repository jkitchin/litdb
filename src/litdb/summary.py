"""Generate newsletter-style summaries of recent articles."""

import json
import re
from collections import defaultdict

import dateparser
from rich import print as richprint

from .chat import get_completion
from .db import get_db
from .utils import get_config


def robust_json_parse(output_text):
    """Robustly parse JSON from LLM output with multiple fallback strategies.

    Args:
        output_text: Raw text output from LLM

    Returns:
        Parsed JSON object or None if parsing fails
    """
    # Strategy 1: Clean up markdown code blocks
    text = output_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            [
                line
                for line in lines
                if not line.startswith("```") and not line.startswith("json")
            ]
        )

    # Strategy 2: Fix unquoted numeric keys
    text = re.sub(r"(\s+)(\d+)(\s*):", r'\1"\2"\3:', text)

    # Strategy 3: Try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 4: Try to extract just the JSON object/array
    # Look for outermost { } or [ ]
    start_brace = text.find("{")
    start_bracket = text.find("[")

    # Determine which comes first
    if start_brace == -1 and start_bracket == -1:
        return None
    elif start_brace == -1:
        start = start_bracket
    elif start_bracket == -1:
        start = start_brace
    else:
        start = min(start_brace, start_bracket)

    # Find matching closing bracket/brace
    depth = 0
    for i in range(start, len(text)):
        if text[i] in "{[":
            depth += 1
        elif text[i] in "}]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    pass
                break

    # Strategy 5: Try using json5-like parsing by adding missing quotes around keys
    # This is a last resort and very permissive
    try:
        # Replace unquoted keys (word chars before colon)
        text = re.sub(r"([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*):", r'\1"\2"\3:', text)
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    return None


# Article types that should be considered (from bibtex.py mapping)
ARTICLE_TYPES = {
    "journal-article",
    "article",
    "review",
    "preprint",
    "monograph",
    "report",
}


def get_articles_since(since_date):
    """Query database for articles added since date.

    Args:
        since_date: String that can be parsed by dateparser

    Returns:
        List of tuples: (source, text, extra_json)
    """
    db = get_db()
    parsed_date = dateparser.parse(since_date)
    if not parsed_date:
        raise ValueError(f"Could not parse date: {since_date}")

    date_str = parsed_date.strftime("%Y-%m-%d")

    # Query for all entries added since the date
    query = """
        SELECT source, text, extra
        FROM sources
        WHERE date(date_added) >= ?
    """

    results = db.execute(query, (date_str,)).fetchall()

    # Filter for articles only
    articles = []
    for source, text, extra in results:
        if extra:
            extra_data = json.loads(extra)
            type_crossref = extra_data.get("type_crossref", "")
            if type_crossref in ARTICLE_TYPES:
                articles.append((source, text, extra_data))

    return articles


def extract_topics_batch(articles, model, batch_size=20):
    """Extract main topics from articles in manageable batches.

    Args:
        articles: List of (source, text, extra_data) tuples
        model: LiteLLM model string
        batch_size: Number of articles to process per API call (default 20)

    Returns:
        Tuple of (all_topics list, article_topics dict mapping source to topics)
    """
    all_topics = []
    article_topics = {}

    # Process articles in chunks
    for batch_start in range(0, len(articles), batch_size):
        batch = articles[batch_start : batch_start + batch_size]
        richprint(
            f"Processing articles {batch_start + 1}-{min(batch_start + batch_size, len(articles))}..."
        )

        # Prepare batch for the LLM
        article_texts = []
        for i, (source, text, extra) in enumerate(batch, 1):
            citation = extra.get("citation", source)
            text_sample = text[:2000] if len(text) > 2000 else text
            article_texts.append(
                f"[Article {i}]\nCitation: {citation}\nText: {text_sample}"
            )

        combined_text = "\n\n".join(article_texts)

        prompt = f"""Analyze these academic articles and identify 3-5 main research topics or themes for EACH article.
Return ONLY a JSON object where keys are article numbers (like "1", "2", "3") and values are arrays of topic strings.

{combined_text}

Return format:
{{
  "1": ["topic1", "topic2", "topic3"],
  "2": ["topic4", "topic5"],
  "3": ["topic1", "topic6", "topic7"]
}}

Return ONLY the JSON object, no other text.
"""

        messages = [{"role": "user", "content": prompt}]

        try:
            # Request more tokens for batch processing (default is often too low)
            output = get_completion(model, messages, max_tokens=8192)
            richprint()  # newline after streaming

            # Use robust JSON parser
            topics_by_article = robust_json_parse(output)

            if not topics_by_article or not isinstance(topics_by_article, dict):
                richprint(
                    f"[yellow]Warning: Could not parse topics from batch {batch_start + 1}-{min(batch_start + batch_size, len(articles))}[/yellow]"
                )
                richprint("[yellow]Raw output (first 500 chars):[/yellow]")
                richprint(output[:500] if output else "N/A")
                # Still add empty entries for this batch
                for source, _, _ in batch:
                    article_topics[source] = []
                continue

            # Build the return structures for this batch
            for i, (source, text, extra) in enumerate(batch, 1):
                topics = topics_by_article.get(str(i), [])
                if not isinstance(topics, list):
                    topics = []
                all_topics.extend(topics)
                article_topics[source] = topics

        except Exception as e:
            richprint(
                f"[yellow]Warning: Error processing batch {batch_start + 1}-{min(batch_start + batch_size, len(articles))}: {e}[/yellow]"
            )
            # Still add empty entries for this batch
            for source, _, _ in batch:
                article_topics[source] = []

    return all_topics, article_topics


def aggregate_topics(all_topics, model):
    """Aggregate all topics into 5-10 main topics with subtopics.

    Args:
        all_topics: List of all topic strings from all articles
        model: LiteLLM model string

    Returns:
        Dict mapping main topics to lists of subtopics
    """
    # Count topic frequencies for better aggregation
    from collections import Counter

    topic_counts = Counter(all_topics)
    topics_text = "\n".join(
        [
            f"- {topic} (mentioned {count} times)"
            for topic, count in topic_counts.most_common()
        ]
    )

    prompt = f"""You are analyzing topics from recent academic articles. Aggregate these topics into 5-10 main research themes, each with relevant subtopics.

Topics from articles:
{topics_text}

Return ONLY a JSON object where keys are main topics and values are arrays of subtopics.

Example format:
{{
  "Machine Learning": ["neural networks", "deep learning", "computer vision"],
  "Climate Science": ["climate modeling", "carbon emissions"]
}}

Return only the JSON, no other text.
"""

    messages = [{"role": "user", "content": prompt}]

    try:
        output = get_completion(model, messages)
        richprint()  # newline

        # Clean up the output
        output = output.strip()
        if output.startswith("```"):
            lines = output.split("\n")
            output = "\n".join(
                [
                    line
                    for line in lines
                    if not line.startswith("```") and not line.startswith("json")
                ]
            )

        topic_structure = json.loads(output)
        if isinstance(topic_structure, dict):
            return topic_structure
        else:
            richprint("[red]Error: LLM did not return valid topic structure[/red]")
            return {}
    except Exception as e:
        richprint(f"[red]Error aggregating topics: {e}[/red]")
        return {}


def classify_articles_batch(articles, topic_structure, model, batch_size=20):
    """Classify articles into topics and subtopics in manageable batches.

    Args:
        articles: List of (source, text, extra_data) tuples
        topic_structure: Dict of main topics to subtopics
        model: LiteLLM model string
        batch_size: Number of articles to process per API call (default 20)

    Returns:
        Dict mapping article source to (main_topic, subtopic) tuples
    """
    result = {}

    # Process articles in chunks
    for batch_start in range(0, len(articles), batch_size):
        batch = articles[batch_start : batch_start + batch_size]
        richprint(
            f"Classifying articles {batch_start + 1}-{min(batch_start + batch_size, len(articles))}..."
        )

        # Prepare batch for the LLM
        article_texts = []
        for i, (source, text, extra) in enumerate(batch, 1):
            citation = extra.get("citation", source)
            text_sample = text[:2000] if len(text) > 2000 else text
            article_texts.append(
                f"[Article {i}]\nCitation: {citation}\nText: {text_sample}"
            )

        combined_text = "\n\n".join(article_texts)
        topics_text = json.dumps(topic_structure, indent=2)

        prompt = f"""Classify EACH article below into ONE main topic and ONE subtopic from the provided structure.

Topic structure:
{topics_text}

Articles:
{combined_text}

Return ONLY a JSON object where keys are article numbers (like "1", "2", "3") and values are objects with "main_topic" and "subtopic" keys.
Use the exact strings from the topic structure.

Return format:
{{
  "1": {{"main_topic": "Machine Learning", "subtopic": "neural networks"}},
  "2": {{"main_topic": "Climate Science", "subtopic": "carbon emissions"}},
  "3": {{"main_topic": "Machine Learning", "subtopic": "computer vision"}}
}}

Return ONLY the JSON object, no other text.
"""

        messages = [{"role": "user", "content": prompt}]

        try:
            # Request more tokens for batch processing (default is often too low)
            output = get_completion(model, messages, max_tokens=8192)
            richprint()

            # Use robust JSON parser
            classifications = robust_json_parse(output)

            if not classifications or not isinstance(classifications, dict):
                richprint(
                    f"[yellow]Warning: Could not parse classifications from batch {batch_start + 1}-{min(batch_start + batch_size, len(articles))}[/yellow]"
                )
                richprint("[yellow]Raw output (first 500 chars):[/yellow]")
                richprint(output[:500] if output else "N/A")
                # Still add empty entries for this batch
                for source, _, _ in batch:
                    result[source] = (None, None)
                continue

            # Build result dict for this batch
            for i, (source, text, extra) in enumerate(batch, 1):
                classification = classifications.get(str(i), {})
                if not isinstance(classification, dict):
                    result[source] = (None, None)
                else:
                    main_topic = classification.get("main_topic")
                    subtopic = classification.get("subtopic")
                    result[source] = (main_topic, subtopic)

        except Exception as e:
            richprint(
                f"[yellow]Warning: Error classifying batch {batch_start + 1}-{min(batch_start + batch_size, len(articles))}: {e}[/yellow]"
            )
            # Still add empty entries for this batch
            for source, _, _ in batch:
                result[source] = (None, None)

    return result


def generate_subtopic_summary(articles, subtopic_name, model):
    """Generate a narrative summary for articles in a subtopic.

    Args:
        articles: List of (source, text, extra_data) tuples
        subtopic_name: Name of the subtopic
        model: LiteLLM model string

    Returns:
        String containing the narrative summary
    """
    # Prepare article summaries for the LLM
    article_texts = []
    for i, (source, text, extra) in enumerate(articles, 1):
        citation = extra.get("citation", source)
        # Use first 1500 chars per article
        text_sample = text[:1500] if len(text) > 1500 else text
        article_texts.append(f"[{i}] {citation}\n{text_sample}")

    combined_text = "\n\n".join(article_texts)

    prompt = f"""Write a narrative summary of recent research on "{subtopic_name}".
Synthesize the findings from these articles, referencing them using numbers like [1], [2], etc.

Articles:
{combined_text}

Write 2-3 paragraphs summarizing the key findings and trends. Reference the articles naturally in your narrative.
"""

    messages = [{"role": "user", "content": prompt}]

    try:
        output = get_completion(model, messages)
        richprint()
        return output
    except Exception as e:
        richprint(f"[red]Error generating summary for {subtopic_name}: {e}[/red]")
        return f"Error generating summary for {subtopic_name}."


def format_org_mode(topic_structure, classified_articles, summaries):
    """Format the newsletter in org-mode syntax.

    Args:
        topic_structure: Dict of main topics to subtopics
        classified_articles: Dict of {topic: {subtopic: [(source, text, extra)]}}
        summaries: Dict of {(topic, subtopic): summary_text}

    Returns:
        String in org-mode format
    """
    output = []
    output.append("#+TITLE: Literature Summary Newsletter")
    output.append("#+DATE: " + dateparser.parse("today").strftime("%Y-%m-%d"))
    output.append("")

    for main_topic in sorted(topic_structure.keys()):
        subtopics = topic_structure[main_topic]

        # Check if this main topic has any articles at all
        has_articles = False
        for subtopic in subtopics:
            articles = classified_articles.get(main_topic, {}).get(subtopic, [])
            if articles:
                has_articles = True
                break

        # Skip this main topic if it has no articles
        if not has_articles:
            continue

        # Print main topic header only if it has articles
        output.append(f"* {main_topic}")
        output.append("")

        for subtopic in subtopics:
            # Check if we have articles for this subtopic
            articles = classified_articles.get(main_topic, {}).get(subtopic, [])
            if not articles:
                continue

            output.append(f"** {subtopic}")
            output.append("")

            # Add the summary
            summary = summaries.get((main_topic, subtopic), "No summary available.")
            output.append(summary)
            output.append("")

            # Add bibliography
            output.append("*** References")
            output.append("")
            for i, (source, text, extra) in enumerate(articles, 1):
                citation = extra.get("citation", source)
                if not citation:
                    citation = f"{extra.get('display_name', 'Unknown')}, {source}"
                output.append(f"{i}. {citation}")
            output.append("")

    return "\n".join(output)


def generate_summary(since="1 week", output_file=None, model=None):
    """Main function to generate the newsletter summary.

    Args:
        since: Time period to look back (dateparser format)
        output_file: Optional filename to save output (defaults to auto-generated name)
        model: LiteLLM model string (uses config default if None)
    """
    config = get_config()

    if model is None:
        llm_config = config.get("llm", {"model": "ollama/llama2"})
        model = llm_config["model"]

    # Generate default output filename if not provided
    if output_file is None:
        # Parse the since date to create a meaningful filename
        parsed_date = dateparser.parse(since)
        if parsed_date:
            # Use the parsed date as the start of the range
            date_str = parsed_date.strftime("%Y-%m-%d")
        else:
            # Fallback to sanitized version of the since string
            date_str = re.sub(r"[^\w\-]", "_", since)

        today = dateparser.parse("today").strftime("%Y-%m-%d")
        output_file = f"literature-summary-{date_str}-to-{today}.org"

    richprint(f"[bold]Generating summary for articles added since {since}[/bold]")
    richprint(f"Using model: {model}")
    richprint(f"Output file: {output_file}\n")

    # Step 1: Get articles
    richprint("[bold cyan]Step 1:[/bold cyan] Fetching articles from database...")
    articles = get_articles_since(since)

    if not articles:
        richprint(f"[yellow]No articles found added since {since}[/yellow]")
        return

    richprint(f"Found {len(articles)} articles\n")

    # Step 2: Extract topics from all articles in batch
    richprint("[bold cyan]Step 2:[/bold cyan] Extracting topics from all articles...")
    all_topics, article_topics = extract_topics_batch(articles, model)

    richprint(f"Extracted {len(all_topics)} total topics\n")

    if not all_topics:
        richprint("[yellow]No topics extracted from articles[/yellow]")
        return

    # Step 3: Aggregate into main topics and subtopics
    richprint("[bold cyan]Step 3:[/bold cyan] Aggregating topics into main themes...")
    topic_structure = aggregate_topics(all_topics, model)

    if not topic_structure:
        richprint("[red]Failed to aggregate topics[/red]")
        return

    richprint(f"Created {len(topic_structure)} main topic categories\n")

    # Step 4: Classify all articles in batch
    richprint("[bold cyan]Step 4:[/bold cyan] Classifying all articles by topic...")
    classifications = classify_articles_batch(articles, topic_structure, model)

    classified_articles = defaultdict(lambda: defaultdict(list))
    for source, text, extra in articles:
        main_topic, subtopic = classifications.get(source, (None, None))
        if main_topic and subtopic:
            classified_articles[main_topic][subtopic].append((source, text, extra))

    richprint("Articles classified\n")

    # Step 5: Generate summaries for each subtopic
    richprint("[bold cyan]Step 5:[/bold cyan] Generating narrative summaries...")
    summaries = {}

    for main_topic, subtopics in classified_articles.items():
        for subtopic, article_list in subtopics.items():
            if article_list:
                richprint(
                    f"Summarizing {main_topic} > {subtopic} ({len(article_list)} articles)..."
                )
                summary = generate_subtopic_summary(article_list, subtopic, model)
                summaries[(main_topic, subtopic)] = summary

    richprint()

    # Step 6: Format as org-mode newsletter
    richprint("[bold cyan]Step 6:[/bold cyan] Formatting newsletter...")
    newsletter = format_org_mode(topic_structure, classified_articles, summaries)

    # Always write to file (output_file is guaranteed to have a value now)
    with open(output_file, "w") as f:
        f.write(newsletter)

    richprint(f"\n[green]Newsletter saved to {output_file}[/green]")
    richprint("[green]Summary generation complete![/green]")
