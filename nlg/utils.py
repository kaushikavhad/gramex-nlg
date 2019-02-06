#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

"""
Miscellaneous utilities.
"""
import os.path as op
from random import choice
import re

from gramex.data import filter as grmfilter  # NOQA: F401
import humanize  # NOQA: F401
import numpy as np
import requests
from spacy import load
from spacy.matcher import Matcher, PhraseMatcher
from tornado.template import Template
from configparser import ConfigParser

nlp = load("en_core_web_sm")

NP_MATCHER = Matcher(nlp.vocab)
NP_MATCHER.add("NP1", None, [{"POS": "PROPN", "OP": "+"}])
NP_MATCHER.add("NP2", None, [{"POS": "NOUN", "OP": "+"}])
NP_MATCHER.add("NP3", None, [{"POS": "ADV", "OP": "+"}, {"POS": "VERB", "OP": "+"}])
NP_MATCHER.add("NP4", None, [{"POS": "ADJ", "OP": "+"}, {"POS": "VERB", "OP": "+"}])
NP_MATCHER.add("QUANT", None, [{"POS": "NUM", "OP": "+"}])

NARRATIVE_TEMPLATE = """
{% autoescape None %}
from nlg import NLGTemplate as N
from nlg import grammar as G
from nlg import utils as U
import pandas as pd

df = None  # set your dataframe here.
narrative = N(\"\"\"
              {{ tmpl }}
              \"\"\",
              tornado_tmpl=True, orgdf=df, fh_args={{ fh_args }},
              G=G, U=U)
print(narrative.render())
"""

config = ConfigParser()
config.read(op.join(op.dirname(__file__), "..", "config.ini"))


def render_search_result(text, results, **kwargs):
    for token, tokenlist in results.items():
        tmpl = [t for t in tokenlist if t.get('enabled', False)][0]
        text = text.replace(token, '{{{{ {} }}}}'.format(tmpl['tmpl']))
    return Template(text).generate(**kwargs).decode('utf-8')


def join_words(x, sep=' '):
    return sep.join(re.findall(r'\w+', x, re.IGNORECASE))


class set_nlg_gramopt(object):
    """Decorator for adding callables to grammar options of the webapp.
    """
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __call__(self, func):
        func.gramopt = True
        for k, v in self.kwargs.items():
            if not getattr(func, k, False):
                setattr(func, k, v)
        return func


def get_phrase_matcher(df):
    matcher = PhraseMatcher(nlp.vocab)
    for col in df.columns[df.dtypes == np.dtype("O")]:
        for val in df[col].unique():
            matcher.add(val, None, nlp(val))
        if str(col).isalpha():
            matcher.add(col, None, nlp(col))
    return matcher


def is_overlap(x, y):
    """Whether the token x is contained within any span in the sequence y."""
    if "NUM" in [c.pos_ for c in x]:
        return False
    return any([x.text in yy for yy in y])


def unoverlap(tokens):
    """From a set of tokens, remove all tokens that are contained within
    others."""
    textmap = {c.text: c for c in tokens}
    text_tokens = textmap.keys()
    newtokens = []
    for token in text_tokens:
        if not is_overlap(textmap[token], text_tokens - {token}):
            newtokens.append(token)
    return [textmap[t] for t in newtokens]


def ner(doc, matcher=NP_MATCHER, match_ids=False, remove_overlap=True):
    """Find all NEs and other nouns in a spacy doc.

    Parameters
    ----------
    doc: spacy.tokens.doc.Doc
        The document in which to search for entities.
    match_ids: list, optional
        IDs from the spacy matcher to filter from the matches.
    remove_overlap: bool, optional
        Whether to remove overlapping tokens from the result.

    Returns
    -------
    list
        List of spacy.token.span.Span objects.
    """
    entities = set()
    for span in doc.ents:
        newtokens = [c for c in span if not c.is_space]
        if newtokens:
            newspan = doc[newtokens[0].i: (newtokens[-1].i + 1)]
            entities.add(newspan)
    if not match_ids:
        entities.update([doc[start:end] for _, start, end in matcher(doc)])
    else:
        for m_id, start, end in matcher(doc):
            if NP_MATCHER.vocab.strings[m_id] in match_ids:
                entities.add(doc[start:end])
    if remove_overlap:
        entities = unoverlap(entities)
    return entities


def sanitize_indices(shape, i, axis=0):
    n = shape[axis]
    if i <= n // 2:
        return i
    return -(n - i)


def sanitize_text(text, d_round=2):
    """All text cleaning and standardization logic goes here."""
    nums = re.findall(r"\d+\.\d+", text)
    for num in nums:
        text = re.sub(num, str(round(float(num), d_round)), text)
    return text


def sanitize_df(df, d_round=2, **options):
    """All dataframe cleaning and standardizing logic goes here."""
    for c in df.columns[df.dtypes == float]:
        df[c] = df[c].round(d_round)
    return df


def sanitize_fh_args(args, func=join_words):
    for k, v in args.items():
        args[k] = [join_words(x) for x in v]
    return args


def humanize_comparison(x, y, bit, lot):
    if x == y:
        return choice(["the same", "identical"])
    if x < y:
        comparative = choice(["higher", "more", "greater"])
    else:
        comparative = choice(["less", "lower"])
    if lot(x, y):
        adj = choice(["a lot", "much"])
    elif bit(x, y):
        adj = choice(["a little", "a bit"])
    else:
        adj = ""
    return " ".join([adj, comparative])


def check_grammar(text):
    host = config.get('languagetool', 'hostname')
    port = config.get('languagetool', 'port')
    apiversion = config.get('languagetool', 'apiversion')
    url = "{}:{}/{}/check?language=en-us&text={}"
    resp = requests.get(url.format(host, port, apiversion, text))
    if resp.status_code == 200:
        return resp.json()['matches']
    return []
