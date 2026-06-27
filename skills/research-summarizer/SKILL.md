---
name: research-summarizer
description: Activates when researching topics for YouTube video scripts. Extracts key claims, statistics, and angles from web sources.
---

# Research Summarizer Skill

This skill guides the ResearchAgent in evaluating source quality, extracting essential data points, and compiling a structured research brief.

## Source Quality Evaluation Guidelines
1. **Credibility Check:** Prioritize sources from academic institutions, registered news organizations, established industry groups, or primary technical documents.
2. **Freshness Assessment:** For fast-moving or tech-focused topics, prioritize sources published in the last 12-24 months.
3. **Fact vs Opinion:** Separate factual claims backed by citations or raw data from opinion editorials. Avoid utilizing purely opinion-based blog posts.

## Extraction Directives
When evaluating each source, extract the following fields precisely:
- **Title:** The headline or name of the article/document.
- **URL:** The direct link to the resource.
- **Key Claims:** Bulleted list of the main, verified arguments made by the author.
- **Relevant Statistics:** Any numerical data, percentages, metrics, or ratios mentioned in the text.
- **Publication Date:** The date the piece was published or last updated.

## Brief Synthesis & Video Angles
Conclude the research process by generating:
1. **Summary:** A concise (~150 words) synthesis of the combined sources, outlining consensus points and points of divergence.
2. **Video Angles:** Three high-impact, narrative angles or hooks for a video script (e.g., "The Counter-Intuitive Truth," "The Historical Breakdown," "The Practical Application").
