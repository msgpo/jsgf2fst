#!/usr/bin/env python3
import os
import sys
import argparse
import re
import json
import logging

import pywrapfst as fst


def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser("fstaccept")
    parser.add_argument("fst", help="Path to FST")
    parser.add_argument("sentences", nargs="+", help="Sentences to parse")
    parser.add_argument(
        "--dont-replace",
        action="store_true",
        help="Disable automation TAG:REPLACE behavior",
    )
    args = parser.parse_args()

    grammar_fst = fst.Fst.read(args.fst)
    intent_name = os.path.splitext(os.path.split(args.fst)[1])[0]
    results = {}

    # Run each sentence through FST acceptor
    for sentence in args.sentences:
        results[sentence] = fstaccept(
            grammar_fst,
            sentence,
            intent_name=intent_name,
            replace_tags=not args.dont_replace,
        )

    json.dump(results, sys.stdout)


# -----------------------------------------------------------------------------


def fstaccept(in_fst, sentence, intent_name=None, replace_tags=True):
    """Recognizes an intent from a sentence using a FST."""

    # Assume lower case, white-space separated tokens
    sentence = sentence.strip().lower()
    words = re.split(r"\s+", sentence)
    intents = []

    try:
        out_fst = apply_fst(words, in_fst)

        # Get output symbols
        out_sentences = fstprintall(out_fst, exclude_meta=False)
        for out_sentence in out_sentences:
            out_intent_name = intent_name
            intent = symbols2intent(
                out_sentence, intent_name=out_intent_name, replace_tags=replace_tags
            )
            intent["intent"]["confidence"] /= len(out_sentences)
            intents.append(intent)
    except:
        # Error, assign blank result
        logging.exception(sentence)

    return intents


# -----------------------------------------------------------------------------


def symbols2intent(
    symbols, eps="<eps>", intent=None, intent_name=None, replace_tags=True
):
    intent = intent or empty_intent()
    tag = None
    tag_symbols = []
    out_symbols = []

    for sym in symbols:
        if sym == "<eps>":
            continue

        if sym.startswith("__begin__"):
            # Begin tag
            tag = sym[9:]
            tag_symbols = []
        elif sym.startswith("__end__"):
            # End tag
            assert tag == sym[7:], f"Mismatched tags: {tag} {sym[7:]}"

            if replace_tags and (":" in tag):
                # Use replacement string in the tag
                tag, tag_value = tag.split(":", maxsplit=1)
            else:
                # Use text between begin/end
                tag_value = " ".join(tag_symbols)

            intent["entities"].append({"entity": tag, "value": tag_value})

            tag = None
        elif sym.startswith("__label__"):
            # Intent label
            if intent_name is None:
                intent_name = sym[9:]
        elif tag:
            # Inside tag
            tag_symbols.append(sym)
            out_symbols.append(sym)
        else:
            # Outside tag
            out_symbols.append(sym)

    intent["text"] = " ".join(out_symbols)
    intent["tokens"] = out_symbols

    if len(out_symbols) > 0:
        intent["intent"]["name"] = intent_name or ""
        intent["intent"]["confidence"] = 1

    return intent


# -----------------------------------------------------------------------------


def fstprintall(
    in_fst,
    out_file=None,
    exclude_meta=True,
    state=None,
    path=None,
    zero_weight=None,
    eps=0,
):
    sentences = []
    path = path or []
    state = state or in_fst.start()
    zero_weight = zero_weight or fst.Weight.Zero(in_fst.weight_type())

    for arc in in_fst.arcs(state):
        path.append(arc)

        if in_fst.final(arc.nextstate) != zero_weight:
            # Final state
            out_syms = in_fst.output_symbols()
            sentence = []
            for p_arc in path:
                if p_arc.olabel != eps:
                    osym = out_syms.find(p_arc.olabel).decode()
                    if exclude_meta and osym.startswith("__"):
                        continue  # skip __label__, etc.

                    if out_file:
                        print(osym, "", end="", file=out_file)
                    else:
                        sentence.append(osym)

            if out_file:
                print("", file=out_file)
            else:
                sentences.append(sentence)
        else:
            # Non-final state
            sentences.extend(
                fstprintall(
                    in_fst,
                    out_file=out_file,
                    state=arc.nextstate,
                    path=path,
                    zero_weight=zero_weight,
                    eps=eps,
                    exclude_meta=exclude_meta,
                )
            )

        path.pop()

    return sentences


# -----------------------------------------------------------------------------

# From:
# https://stackoverflow.com/questions/9390536/how-do-you-even-give-an-openfst-made-fst-input-where-does-the-output-go


def linear_fst(elements, automata_op, keep_isymbols=True, **kwargs):
    """Produce a linear automata."""
    compiler = fst.Compiler(
        isymbols=automata_op.input_symbols().copy(),
        acceptor=keep_isymbols,
        keep_isymbols=keep_isymbols,
        **kwargs,
    )

    for i, el in enumerate(elements):
        print("{} {} {}".format(i, i + 1, el), file=compiler)
    print(str(i + 1), file=compiler)

    return compiler.compile()


def apply_fst(elements, automata_op, is_project=True, **kwargs):
    """Compose a linear automata generated from `elements` with `automata_op`.

    Args:
        elements (list): ordered list of edge symbols for a linear automata.
        automata_op (Fst): automata that will be applied.
        is_project (bool, optional): whether to keep only the output labels.
        kwargs:
            Additional arguments to the compiler of the linear automata .
    """
    linear_automata = linear_fst(elements, automata_op, **kwargs)
    out = fst.compose(linear_automata, automata_op)
    if is_project:
        out.project(project_output=True)
    return out


# -----------------------------------------------------------------------------


def empty_intent():
    return {"text": "", "intent": {"name": "", "confidence": 0}, "entities": []}


# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
