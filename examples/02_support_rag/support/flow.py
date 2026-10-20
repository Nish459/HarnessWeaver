"""The support flow: route the question, retrieve articles, answer citing them.

The app owns these steps; the session governs each one:

1. ``decide`` fires ``route.decide``: the rules stage, then the lexical stage.
2. ``fetch`` retrieves articles, re-checks each ACL against the caller's tenant
   and principal, labels them untrusted and runs the context guards, which drop
   an article carrying an injection. Only what is left reaches the model.
3. ``generate`` renders the versioned prompt, calls the model through the
   gateway, and runs the output guards: the citation check repairs an answer
   whose sentences don't cite a retrieved article.

The same function serves the Session style (``run.py``) and the ``support`` task
(``harness.run``, and the evals).
"""

import harnessweaver as hw
from support.models import Reply

NO_ANSWER = "I don't know; a support agent will follow up."


async def answer(s: hw.Session, question: str) -> Reply:
    """Answer one customer question from the help center.

    Returns:
        The question's intent, the answer, and the ids of the articles it could cite.
    """
    route = await s.decide("intent", text=question)
    articles = await s.context("help").fetch(question)
    if not articles:  # nothing this customer may read answers it: don't let the model guess
        return Reply(intent=str(route.choice), answer=NO_ANSWER, sources=[])
    listing = "\n".join(f"[{a.id}] {a.content}" for a in articles)
    text = await s.generate(
        prompt="answer@1", question=question, intent=route.choice, articles=listing
    )
    return Reply(intent=str(route.choice), answer=str(text), sources=[a.id for a in articles])
