from __future__ import absolute_import
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sklearn.feature_extraction.text import VectorizerMixin
from sklearn.pipeline import FeatureUnion

from eli5.base import (
    DocWeightedSpans, WeightedSpans, FeatureWeights, FeatureWeight)
from eli5.formatters import FormattedFeatureName
from eli5.sklearn.unhashing import InvertableHashingVectorizer
from eli5.sklearn._span_analyzers import build_span_analyzer


def get_weighted_spans(doc, vec, feature_weights):
    # type: (Any, Any, FeatureWeights) -> Optional[WeightedSpans]
    """ If possible, return a dict with preprocessed document and a list
    of spans with weights, corresponding to features in the document.
    """
    if isinstance(vec, FeatureUnion):
        return _get_weighted_spans_from_union(doc, vec, feature_weights)
    else:
        result = _get_doc_weighted_spans(doc, vec, feature_weights)
        if result is not None:
            found_features, doc_weighted_spans = result
            return WeightedSpans(
                [doc_weighted_spans],
                other=_get_other(feature_weights, [('', found_features)]),
            )


FoundFeatures = Dict[Tuple[str, int], float]


def _get_doc_weighted_spans(doc, vec, feature_weights, feature_fn=None):
    # type: (Any, Any, FeatureWeights, Callable[[str], str]) -> Optional[Tuple[FoundFeatures, DocWeightedSpans]]
    if isinstance(vec, InvertableHashingVectorizer):
        vec = vec.vec
    if not isinstance(vec, VectorizerMixin):
        return None

    span_analyzer, preprocessed_doc = build_span_analyzer(doc, vec)
    if span_analyzer is None:
        return None

    # (group, idx) is a feature key here
    feature_weights_dict = {
        f: (fw.weight, (group, idx)) for group in ['pos', 'neg']
        for idx, fw in enumerate(getattr(feature_weights, group))
        for f in _get_features(fw.feature, feature_fn)}

    spans = []
    found_features = {}
    for f_spans, feature in span_analyzer(preprocessed_doc):
        try:
            weight, key = feature_weights_dict[feature]
        except KeyError:
            pass
        else:
            spans.append((feature, f_spans, weight))
            found_features[key] = weight

    return found_features, DocWeightedSpans(
        document=preprocessed_doc,
        spans=spans,
        preserve_density=vec.analyzer.startswith('char'),
    )


def _get_features(feature, feature_fn=None):
    if isinstance(feature, list):
        features = [f['name'] for f in feature]
    else:
        features = [feature]
    if feature_fn:
        features = list(filter(None, map(feature_fn, features)))
    return features


def _get_weighted_spans_from_union(doc, vec_union, feature_weights):
    # type: (Any, FeatureUnion, FeatureWeights) -> Optional[WeightedSpans]
    docs_weighted_spans = []
    named_found_features = []
    for vec_name, vec in vec_union.transformer_list:
        vec_prefix = '{}__'.format(vec_name)
        feature_fn = lambda x: (
            x[len(vec_prefix):] if x.startswith(vec_prefix) else None)
        result = _get_doc_weighted_spans(doc, vec, feature_weights, feature_fn)
        if result:
            found_features, doc_weighted_spans = result
            doc_weighted_spans.vec_name = vec_name
            named_found_features.append((vec_name, found_features))
            docs_weighted_spans.append(doc_weighted_spans)

    if docs_weighted_spans:
        return WeightedSpans(
            docs_weighted_spans,
            other=_get_other(feature_weights, named_found_features),
        )


def _get_other(feature_weights, named_found_features):
    # type: (FeatureWeights, List[Tuple[str, FoundFeatures]]) -> FeatureWeights
    # search for items that were not accounted at all.
    other_items = []
    accounted_keys = set()  # type: Set[Tuple[str, int]]
    all_found_features = {}
    for _, found_features in named_found_features:
        all_found_features.update(found_features)

    for group in ['pos', 'neg']:
        for idx, fw in enumerate(getattr(feature_weights, group)):
            key = (group, idx)
            if key not in all_found_features and key not in accounted_keys:
                other_items.append(fw)
                accounted_keys.add(key)

    for vec_name, found_features in named_found_features:
        if found_features:
            other_items.append(FeatureWeight(
                feature=FormattedFeatureName(
                    '{}Highlighted in text (sum)'.format(
                        '{}: '.format(vec_name) if vec_name else '')),
                weight=sum(found_features.values())))

    other_items.sort(key=lambda x: abs(x.weight), reverse=True)
    return FeatureWeights(
        pos=[fw for fw in other_items if fw.weight >= 0],
        neg=[fw for fw in other_items if fw.weight < 0],
        pos_remaining=feature_weights.pos_remaining,
        neg_remaining=feature_weights.neg_remaining,
    )
