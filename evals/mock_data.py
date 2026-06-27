"""Mock dataset and generator helper for ContentOS evaluations mock testing."""

import json
from google.adk.models.llm_response import LlmResponse
from google.genai import types

CURRENT_TOPIC_TEXT = ""

MOCK_EVALS_DATA = {
    "why gen z is burnt out before they even start their careers": {
        "slug": "case_01_genz_burnout",
        "research": {
            "topic": "why gen z is burnt out before they even start their careers",
            "sources": [
                {
                    "title": "Deloitte 2024 Gen Z and Millennial Survey",
                    "url": "https://www2.deloitte.com/global/en/pages/about-deloitte/articles/genzmillennialsurvey.html",
                    "key_claims": ["Cost of living is Gen Z's top concern.", "High stress and burnout persist due to workload."],
                    "stats": ["40% of Gen Zs feel stressed constantly.", "35% report feeling burned out."],
                    "date": "2024-05-15"
                },
                {
                    "title": "McKinsey Mental Health Index 2023",
                    "url": "https://www.mckinsey.com/mgi/our-research/delivering-on-the-promise-of-employer-supported-mental-health",
                    "key_claims": ["Gen Z reports the lowest mental well-being.", "Pre-career stress is fueled by economic instability."],
                    "stats": ["Gen Z is 3 times more likely to report poor mental health.", "Pre-career stress affects 55% of grads."],
                    "date": "2023-10-12"
                },
                {
                    "title": "American Psychological Association: Stress in America",
                    "url": "https://www.apa.org/news/press/releases/stress/2023/collective-trauma-gen-z",
                    "key_claims": ["Gen Z is stressed about future economy and career barriers.", "Workplace expectations lead to anxiety."],
                    "stats": ["72% list work and economy as stressors.", "64% feel overwhelmed by career paths."],
                    "date": "2023-11-01"
                }
            ],
            "summary": "gen z is facing unprecedented stress levels before entering the workforce, driven by cost of living concerns, economic instability, and high career expectations. surveys show they report the lowest mental well-being of any generation, with over forty percent feeling anxious most of the time. this pre-career burnout is not a sign of laziness; rather, it is a rational response to entering a game where the entry price has doubled while the payouts are halved. they face systemic financial claustrophobia, shifting workplace dynamics, and extreme pressure to plan ten years ahead in a highly volatile world. the combination of these factors makes the transition from education to employment extremely exhausting, leading to early crash points.",
            "angles": ["The Price of Ambition", "The Pre-Career Crash", "Rethinking the 9-to-5 Dream"],
            "refine_required": False
        },
        "script": {
            "script": (
                "# Hook\n"
                "why are you already exhausted and you haven't even started your first real job yet? let's talk about why gen z is burnt out before the career race even begins.\n\n"
                "# Section 1: The Cost of Existing\n"
                "point one. you're entering a game where the entry price is double and the payout is halved. according to deloitte, cost of living is your top concern, and 40% of you feel anxious constantly. you aren't lazy; you're financially claustrophobic. (https://www2.deloitte.com/global/en/pages/about-deloitte/articles/genzmillennialsurvey.html)\n\n"
                "# Section 2: The Mental Mismatch\n"
                "point two. the workplace was built for boomers, but you're paying the mental tax. mckinsey reports gen z has the lowest well-being, and grads are 3x more likely to report poor mental health than older generations. the hustle culture lied. (https://www.mckinsey.com/mgi/our-research/delivering-on-the-promise-of-employer-supported-mental-health)\n\n"
                "# Section 3: Mismatch Anxiety\n"
                "point three. you're pressured to have a 10-year plan in a world that can't plan 10 days ahead. over 70% of you list the economy as a major stress source. trying to find stability in a collapse is exhausting. (https://www.apa.org/news/press/releases/stress/2023/collective-trauma-gen-z)\n\n"
                "# CTA\n"
                "are you already burnt out or just realistic? drop your thoughts below and subscribe if you're done with corporate fluff."
            ),
            "word_count": 182,
            "estimated_duration": "1-2 minutes",
            "sources_cited": [
                "https://www2.deloitte.com/global/en/pages/about-deloitte/articles/genzmillennialsurvey.html",
                "https://www.mckinsey.com/mgi/our-research/delivering-on-the-promise-of-employer-supported-mental-health",
                "https://www.apa.org/news/press/releases/stress/2023/collective-trauma-gen-z"
            ],
            "hook": "why are you already exhausted and you haven't even started your first real job yet? let's talk about why gen z is burnt out before the career race even begins."
        },
        "seo": {
            "titles": [
                "why gen z is burnt out before 9-to-5",
                "is gen z already too tired to work?",
                "3 reasons gen z is burnt out before day 1"
			],
            "description": "Explaining the root causes of pre-career burnout in Gen Z, including cost of living and economic anxiety.",
            "tags": ["gen z", "burnout", "workplace stress", "career advice", "mental health"],
            "thumbnail_brief": "A split image of a graduation cap next to a battery icon showing 1% charge.",
            "chapter_markers": ["0:00 - Hook", "0:25 - Cost of Existing", "1:00 - Hustle Culture Lie", "1:35 - CTA"]
        }
    },
    "the psychology behind why we procrastinate on things we actually care about": {
        "slug": "case_02_procrastination",
        "research": {
            "topic": "the psychology behind why we procrastinate on things we actually care about",
            "sources": [
                {
                    "title": "Solving the Procrastination Puzzle by Dr. Timothy Pychyl",
                    "url": "https://www.psychologytoday.com/us/blog/dont-delay/202003/solving-the-procrastination-puzzle",
                    "key_claims": ["Procrastination is an emotion regulation problem, not a time management problem.", "We avoid tasks to seek short-term mood repair."],
                    "stats": ["20% of adults are chronic procrastinators.", "Procrastination is linked to higher stress and depression."],
                    "date": "2020-03-10"
                },
                {
                    "title": "Harvard Business Review: Why You Procrastinate",
                    "url": "https://hbr.org/2019/03/why-you-procrastinate-it-has-to-do-with-emotions-not-time",
                    "key_claims": ["Amygdala hijack causes us to prioritize immediate relief over long-term goals.", "Self-compassion reduces procrastination recurrence."],
                    "stats": ["Procrastinating on important tasks leads to a 25% increase in anxiety levels."],
                    "date": "2019-03-25"
                }
            ],
            "summary": "procrastination is primarily an emotional regulation issue where the brain prioritizes immediate mood repair over future rewards. when a task feels high-stakes or is tied to our self-worth, the amygdala treats the pressure as a threat and prompts avoidance behavior. standard time management systems fail because they ignore this emotional component. dr. timothy pychyl's research shows that checking your phone or procrastinating is a subconscious attempt to escape feeling small or overwhelmed. by choosing short-term relief, chronic procrastinators experience a twenty-five percent spike in long-term anxiety. the key to breaking this cycle lies in self-compassion and taking action without waiting to feel motivated.",
            "angles": ["The Mood Repair Trap", "Your Amygdala is Lying to You", "High Stakes, Zero Action"],
            "refine_required": False
        },
        "script": {
            "script": (
                "# Hook\n"
                "why do you ignore the exact tasks that could change your life? it's not because you're lazy, it's because your brain is scared.\n\n"
                "# Section 1: The Mood Repair Lie\n"
                "point one. procrastination isn't a time management problem. dr. timothy pychyl's research shows it's emotion regulation. your brain wants short-term mood repair. you check your phone because the task makes you feel small. (https://www.psychologytoday.com/us/blog/dont-delay/202003/solving-the-procrastination-puzzle)\n\n"
                "# Section 2: Amygdala Hijack\n"
                "point two. when a task actually matters, your self-worth is on the line. harvard business review explains that your amygdala treats the pressure as a threat. it hijacks your focus to escape the stress, causing a 25% spike in chronic anxiety. (https://hbr.org/2019/03/why-you-procrastinate-it-has-to-do-with-emotions-not-time)\n\n"
                "# Section 3: The Cure is Kindness\n"
                "point three. beating yourself up just makes the next attempt harder. self-compassion breaks the anxiety loop. stop waiting to 'feel like' doing it. you never will.\n\n"
                "# CTA\n"
                "what are you avoiding right now? drop a comment and subscribe if you're ready to stop hiding from your goals."
            ),
            "word_count": 168,
            "estimated_duration": "1-2 minutes",
            "sources_cited": [
                "https://www.psychologytoday.com/us/blog/dont-delay/202003/solving-the-procrastination-puzzle",
                "https://hbr.org/2019/03/why-you-procrastinate-it-has-to-do-with-emotions-not-time"
            ],
            "hook": "why do you ignore the exact tasks that could change your life? it's not because you're lazy, it's because your brain is scared."
        },
        "seo": {
            "titles": [
                "why you procrastinate on things you love",
                "is it laziness or amygdala hijack?",
                "the real reason you avoid important work"
            ],
            "description": "Unpacking the science of procrastination. Why your brain treats important tasks as threats and how to break the cycle.",
            "tags": ["procrastination", "psychology", "mental health", "productivity hacks", "motivation"],
            "thumbnail_brief": "A brain holding a shield against a to-do list checkbox.",
            "chapter_markers": ["0:00 - Hook", "0:20 - Emotional Regulation", "0:55 - Amygdala Threat", "1:30 - CTA"]
        }
    },
    "why most productivity advice doesn't work for people with ADHD": {
        "slug": "case_03_adhd_productivity",
        "research": {
            "topic": "why most productivity advice doesn't work for people with ADHD",
            "sources": [
                {
                    "title": "CHADD: ADHD and Executive Dysfunction",
                    "url": "https://chadd.org/about-adhd/executive-function-skills/",
                    "key_claims": ["ADHD is a disorder of interest, not attention.", "Standard linear planners fail because they assume consistent executive function."],
                    "stats": ["ADHD affects executive functioning in 90% of diagnosed adults.", "Traditional productivity methods fail for 85% of people with ADHD."],
                    "date": "2023-08-15"
                },
                {
                    "title": "ADDitude Magazine: The ADHD Brain Deficit",
                    "url": "https://www.additudemag.com/adhd-brain-chemistry-dopamine-interest-nervous-system/",
                    "key_claims": ["The ADHD nervous system is interest-based, not importance-based.", "Dopamine deficits make routine tasks physically painful to initiate."],
                    "stats": ["ADHD brains produce less tonic dopamine, leading to constant stimulation-seeking."],
                    "date": "2024-01-20"
                }
            ],
            "summary": "productivity systems are designed for neurotypical brains using importance-based motivators such as deadlines and standard rewards. however, the adhd brain operates on a dopamine-deficient, interest-based nervous system that requires novelty, urgency, or intrinsic interest to engage. traditional advice like breaking tasks down and sticking to rigid routines fails for eighty-five percent of people with adhd because their executive functioning is cyclical and interest-driven. standard linear planners do not accommodate executive dysfunction deficits. to work effectively, neurodivergent individuals must shift from neurotypical habits to interest-based strategies like body-doubling, task gamification, and matching task lists directly to their current dopamine levels. this customized approach unlocks real focus and consistency.",
            "angles": ["The Dopamine Gap", "Planners Won't Save You", "Designing for Neurodivergence"],
            "refine_required": False
        },
        "script": {
            "script": (
                "# Hook\n"
                "buying another planner won't cure your executive dysfunction. here is why typical productivity advice is gaslighting your adhd brain.\n\n"
                "# Section 1: The Dopamine Deficit\n"
                "point one. your brain is dopamine-deficient. additude magazine reports that standard systems assume importance motivators work. they don't. the adhd nervous system is interest-based, not importance-based. if a task is boring, it is physically painful to start. (https://www.additudemag.com/adhd-brain-chemistry-dopamine-interest-nervous-system/)\n\n"
                "# Section 2: Executive Dysfunction\n"
                "point two. standard productivity advice tells you to break tasks down and stick to a routine. chadd shows this fails because adhd is an executive function deficit. standard linear planners fail for 85% of us because our energy is cyclical, not linear. (https://chadd.org/about-adhd/executive-function-skills/)\n\n"
                "# Section 3: The Interest Hack\n"
                "point three. stop trying to force neurotypical habits. work with your interest-based nervous system. use body-doubling, inject novelty, or gamify the process. matching the task to your current dopamine level is the only way.\n\n"
                "# CTA\n"
                "how many half-filled notebooks do you own? tell me below and subscribe for productivity advice that actually works for neurodivergent brains."
            ),
            "word_count": 178,
            "estimated_duration": "1-2 minutes",
            "sources_cited": [
                "https://www.additudemag.com/adhd-brain-chemistry-dopamine-interest-nervous-system/",
                "https://chadd.org/about-adhd/executive-function-skills/"
            ],
            "hook": "buying another planner won't cure your executive dysfunction. here is why typical productivity advice is gaslighting your adhd brain."
        },
        "seo": {
            "titles": [
                "why planners fail your adhd brain",
                "is it ADHD or just bad advice?",
                "how to build a productivity system for ADHD"
            ],
            "description": "Explaining why typical time-management techniques fail neurodivergent brains and how interest-based nervous systems actually function.",
            "tags": ["adhd", "productivity tips", "executive dysfunction", "neurodivergent", "adhd hacks"],
            "thumbnail_brief": "A stack of 10 blank journals with a sticky note saying 'try harder'.",
            "chapter_markers": ["0:00 - Hook", "0:25 - Dopamine Deficit", "1:05 - Executive Dysfunction", "1:40 - CTA"]
        }
    },
    "how social media is rewiring our ability to be bored": {
        "slug": "case_04_social_media_boredom",
        "research": {
            "topic": "how social media is rewiring our ability to be bored",
            "sources": [
                {
                    "title": "The Dopamine Loop: Social Media and ADHD Symptoms",
                    "url": "https://www.psychologytoday.com/us/blog/dopamine-loop",
                    "key_claims": ["Social media platforms micro-dose dopamine, raising the excitement threshold.", "Constant scrolling makes normal, quiet moments feel extremely boring."],
                    "stats": ["Average screen time for teens is 7 hours a day.", "Boredom tolerance decreased by 40% over the last decade."],
                    "date": "2024-03-12"
                },
                {
                    "title": "Boredom is Good for the Brain: Nature Study",
                    "url": "https://www.nature.com/articles/boredom-and-default-mode-network",
                    "key_claims": ["Boredom activates the default mode network (DMN), which is critical for creativity.", "Avoiding boredom stops deep cognitive processing."],
                    "stats": ["DMN activity drops by 50% when constantly stimulated by notifications."],
                    "date": "2023-09-05"
                }
            ],
            "summary": "social media platforms are engineered to micro-dose dopamine through infinite scrolls and instant notifications. this constant digital stimulation raises our neurochemical baseline threshold, which makes normal offline moments feel intolerably boring. a nature study shows that constant alerts drop default mode network activity in the brain by fifty percent. the default mode network is critical for deep creative thoughts and passive consolidation of memories. when we avoid boredom by scrolling, we are starving our cognitive capacity. reclaiming our focus requires us to deliberately rebuild our boredom tolerance and allow unstructured quiet moments back into our daily routines. by reclaiming this blank mental space, we allow our brains to recharge and generate original ideas.",
            "angles": ["The Infinite Scroll Trap", "The Dopamine Baseline Shift", "Why Boredom is Your Superpower"],
            "refine_required": False
        },
        "script": {
            "script": (
                "# Hook\n"
                "you can't even sit through a 30-second silence without reaching for your phone. here is how social media has deleted your ability to be bored.\n\n"
                "# Section 1: The Dopamine Trap\n"
                "point one. social media platforms micro-dose dopamine to keep you scrolling. psychology today explains this constant stimulation raises your neurochemical baseline. normal quiet moments aren't actually boring; your brain is just suffering withdrawal. (https://www.psychologytoday.com/us/blog/dopamine-loop)\n\n"
                "# Section 2: Default Mode Shutdown\n"
                "point two. boredom is critical for deep thoughts. a nature study shows that constant notifications drop default mode network activity by 50%. if you never let your mind wander, you are starving your own creativity. (https://www.nature.com/articles/boredom-and-default-mode-network)\n\n"
                "# Section 3: Reclaim the Quiet\n"
                "point three. you need to rebuild your boredom tolerance. stop micro-dosing stimulation in elevators or checkout lines. let yourself be bored. it's the only way to get your focus back.\n\n"
                "# CTA\n"
                "when was the last time you did absolutely nothing? drop a comment and subscribe to reclaim your focus."
            ),
            "word_count": 172,
            "estimated_duration": "1-2 minutes",
            "sources_cited": [
                "https://www.psychologytoday.com/us/blog/dopamine-loop",
                "https://www.nature.com/articles/boredom-and-default-mode-network"
            ],
            "hook": "you can't even sit through a 30-second silence without reaching for your phone. here is how social media has deleted your ability to be bored."
        },
        "seo": {
            "titles": [
                "why you can't stand being bored",
                "is social media deleting your creativity?",
                "3 reasons to let yourself be bored"
            ],
            "description": "Unpacking how constant social media notifications rewire our dopamine baselines and kill default mode network creativity.",
            "tags": ["social media addiction", "dopamine detox", "boredom benefits", "mental focus", "creativity tips"],
            "thumbnail_brief": "A hand dropping a glowing smartphone into a dark pool of water.",
            "chapter_markers": ["0:00 - Hook", "0:25 - The Dopamine Loop", "1:00 - Brain Activation", "1:35 - CTA"]
        }
    },
    "why therapy has become a personality trait for millennials": {
        "slug": "case_05_millennial_therapy",
        "research": {
            "topic": "why therapy has become a personality trait for millennials",
            "sources": [
                {
                    "title": "The Rise of Therapy Speak: New Yorker",
                    "url": "https://www.newyorker.com/culture/cultural-comment/the-rise-of-therapy-speak",
                    "key_claims": ["Therapy speak (boundaries, gaslighting, toxic) is used to justify selfish behavior.", "Clinical terms are co-opted to avoid interpersonal conflict."],
                    "stats": ["Usage of the term 'gaslighting' increased by 300% on social platforms.", "45% of millennials utilize therapy buzzwords weekly in text chats."],
                    "date": "2023-05-18"
                },
                {
                    "title": "Millennial Identity and Self-Care: Pew Research",
                    "url": "https://www.pewresearch.org/social-trends/2023/12/millennial-self-care-identities",
                    "key_claims": ["Millennials view mental health work as a primary identifier of their generation.", "Therapy is worn as a badge of honor or moral superiority."],
                    "stats": ["60% of millennials list therapy as an important aspect of their identity."],
                    "date": "2023-12-10"
                }
            ],
            "summary": "therapy terminology has shifted from a private clinical tool to a public badge of identity for millennials. co-opting clinical terms like gaslighting, boundaries, or narcissism allows individuals to frame standard relationship friction as medical abuse, effectively bypassing normal conflict resolution and self-reflection. pew research indicates that sixty percent of millennials view mental health work as a primary identifier of their generation, treating therapy as a brand of moral superiority. weaponizing clinical vocabulary under the guise of self-care can isolate people rather than heal them. true emotional maturity requires moving past clinical buzzwords and engaging in messy, authentic human connections. ultimately, healing is about vulnerability and direct conversation, not clinical classification tags.",
            "angles": ["The Trap of Therapy Speak", "Self-Care or Self-Absorption?", "The New Moral Superiority"],
            "refine_required": False
        },
        "script": {
            "script": (
                "# Hook\n"
                "saying someone is gaslighting you when they just disagree is not healing, it's avoiding conflict. let's talk about why therapy speak has become a personality trait.\n\n"
                "# Section 1: The Rise of Buzzwords\n"
                "point one. you are weaponizing clinical vocabulary. the new yorker reports a 300% increase in term abuse like boundaries or gaslighting. it isn't therapeutic; it's co-opting medical terminology to justify avoiding normal interpersonal struggles. (https://www.newyorker.com/culture/cultural-comment/the-rise-of-therapy-speak)\n\n"
                "# Section 2: Badge of Superiority\n"
                "point two. therapy is no longer just healing; it's a social brand. pew research shows 60% of millennials treat therapy as a core identity marker. sharing diagnostic labels is the new moral superiority card. (https://www.pewresearch.org/social-trends/2023/12/millennial-self-care-identities)\n\n"
                "# Section 3: Real Connection\n"
                "point three. talking like a therapist doesn't make you emotionally mature. it actually isolates you. stop hiding behind clinical walls and start having real, messy human conversations.\n\n"
                "# CTA\n"
                "do you use therapy speak or are you just authentic? comment below and subscribe if you're done with buzzwords."
            ),
            "word_count": 175,
            "estimated_duration": "1-2 minutes",
            "sources_cited": [
                "https://www.newyorker.com/culture/cultural-comment/the-rise-of-therapy-speak",
                "https://www.pewresearch.org/social-trends/2023/12/millennial-self-care-identities"
            ],
            "hook": "saying someone is gaslighting you when they just disagree is not healing, it's avoiding conflict. let's talk about why therapy speak has become a personality trait."
        },
        "seo": {
            "titles": [
                "why therapy speak is toxic",
                "did therapy become a millennial brand?",
                "3 problems with weaponized therapy terms"
            ],
            "description": "Analyzing the rise of therapy buzzwords and clinical language in millennial friendships and social identity.",
            "tags": ["therapy speak", "self care culture", "millennial traits", "relationships", "mental health chat"],
            "thumbnail_brief": "A dictionary with a sticker of a smiley face covering the word 'Gaslight'.",
            "chapter_markers": ["0:00 - Hook", "0:25 - Weaponized Vocab", "1:00 - Identity Badge", "1:35 - CTA"]
        }
    }
}

async def mock_generate_content_async(self, llm_request, stream=False):
    global CURRENT_TOPIC_TEXT
    topic_key = CURRENT_TOPIC_TEXT or ""
    
    # Try to extract topic from llm_request contents if not set
    if not topic_key:
        for content in llm_request.contents:
            if content.parts:
                for part in content.parts:
                    if part.text and len(part.text) > 5 and not part.text.startswith("{") and not part.text.startswith("#"):
                        topic_key = part.text.strip()
                        break
            if topic_key:
                break

    # Standardize lookup
    matched_key = None
    if topic_key:
        for k in MOCK_EVALS_DATA.keys():
            if k.lower() in topic_key.lower() or topic_key.lower() in k.lower():
                matched_key = k
                break
                
    if not matched_key:
        matched_key = "why gen z is burnt out before they even start their careers"
        
    topic_data = MOCK_EVALS_DATA[matched_key]
    
    # Use topic_key as prompt for outputs if relevant
    display_topic = topic_key or matched_key

    mock_brief = topic_data["research"]
    mock_script = topic_data["script"]
    mock_seo = topic_data["seo"]

    system_instr = ""
    if hasattr(llm_request, "config") and llm_request.config and llm_request.config.system_instruction:
        instr = llm_request.config.system_instruction
        if isinstance(instr, str):
            system_instr = instr.lower()
        elif hasattr(instr, "parts"):
            system_instr = "".join(p.text for p in instr.parts if p.text).lower()

    is_research = "web_search" in system_instr or "summarizer" in system_instr
    is_script = "sibling" in system_instr or "narration" in system_instr or "scriptwriting" in system_instr
    is_review = "reviewagent" in system_instr or "request_review" in system_instr or "unverified_claims" in system_instr
    is_seo = ("seo" in system_instr or "chapter_markers" in system_instr or "titles" in system_instr) and not is_review

    if is_research:
        has_search_response = False
        for content in llm_request.contents:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if part.function_response and part.function_response.name == "web_search":
                        has_search_response = True

        if has_search_response:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=json.dumps(mock_brief))]
                )
            )
        else:
            fc = types.FunctionCall(
                name="web_search",
                id="fc-web-search",
                args={"query": display_topic}
            )
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc)]
                )
            )

    elif is_script:
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(mock_script))]
            )
        )

    elif is_seo:
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=json.dumps(mock_seo))]
            )
        )

    elif is_review:
        has_approve = False
        has_save_package_response = False
        actual_saved_dir = f"evals/runs/{topic_data['slug']}"

        for content in llm_request.contents:
            if content.role == "user" and content.parts:
                for part in content.parts:
                    if part.function_response:
                        if part.function_response.name == "request_review":
                            res_val = part.function_response.response.get("result", "")
                            if "APPROVE" in res_val:
                                has_approve = True
                        if part.function_response.name == "save_final_package":
                            has_save_package_response = True

        if has_save_package_response:
            text_content = json.dumps({
                "status": "approved",
                "saved_directory": actual_saved_dir,
                "message": "Successfully saved package and approved."
            })
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=text_content)]
                )
            )
        elif has_approve:
            fc = types.FunctionCall(
                name="save_final_package",
                id="fc-save-package",
                args={
                    "topic": display_topic,
                    "research_brief_json": json.dumps(mock_brief),
                    "script_markdown": mock_script["script"],
                    "seo_package_json": json.dumps(mock_seo),
                    "approved_by": "human"
                }
            )
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc)]
                )
            )
        else:
            fc = types.FunctionCall(
                name="request_review",
                id="fc-request-review",
                args={
                    "hook": mock_script["hook"],
                    "word_count": mock_script["word_count"],
                    "estimated_duration": mock_script["estimated_duration"],
                    "titles": mock_seo["titles"],
                    "tags": mock_seo["tags"],
                    "thumbnail_brief": mock_seo["thumbnail_brief"],
                    "sources_cited": mock_script["sources_cited"],
                    "unverified_claims_detected": False
                }
            )
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc)]
                )
            )
