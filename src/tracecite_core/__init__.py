# -*- coding: utf-8 -*-
"""TraceCite Core: generic, dependency-free text evidence primitives.

core 只保留通用默认：
- segmenter: Segmenter 基类 · FormatSegmenter(声明式) · JsonLineSegmenter · RawTextSegmenter · RegexSegmenter
- source: FileSource(文件路径) · 编码
- preprocess: charset/grep 内置 action
- text_filter: AC/regex/字面量 匹配 · 以什么开头/结尾
- Device and application formats live in the TraceCite Mobile layer.

Constraint: this package never imports TraceCite Mobile or company extensions.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .records import Record, estimate_tokens
from .segmenter import (
    FormatSegmenter,
    JsonLineSegmenter,
    RawTextSegmenter,
    RegexSegmenter,
    Segmenter,
    available_segmenters,
    build_segmenter,
    detect_segmenter_kind,
    register_format,
    register_segmenter,
    register_segmenter_detector,
)
from .source import (
    ArchiveSource,
    LiveSource,
    Source,
    SourceError,
    SourceResolution,
    StaticFileSource,
    available_source_providers,
    build_source,
    register_source_provider,
    resolve_paths,
    resolve_source_spec,
)
from .plugin_sdk import (
    PLUGIN_API_VERSION,
    PluginAPI,
    load_entrypoint_plugins,
    loaded_plugins,
)
from .events import (
    AnalysisEvent,
    EventRef,
    EventTransformContext,
    EventTransformError,
    apply_event_transformers,
    available_event_transformers,
    events_from_filter_result,
    register_event_transformer,
    write_events_jsonl,
)
from .run import (
    AnalysisRun,
    RUN_SCHEMA_VERSION,
    RunFile,
    RunIntegrityError,
    RunWorkspace,
    verify_manifest,
)
from .text_filter import (
    FilterError,
    FilterResult,
    filter_text,
    filter_texts,
    pattern_from_terms,
    parse_time_arg,
    record_timestamp,
    reference_datetime,
    text_time_range,
    top_terms_in_text,
)
from .matcher import PatternComponent, coerce_pattern_components
from .survey import (
    SurveyError,
    SurveySummary,
    survey,
    survey_file,
)
from .sample import (
    DEFAULT_SAMPLE_CHARS,
    DEFAULT_SAMPLE_COUNT,
    MAX_SAMPLE_CHARS,
    MAX_SAMPLE_COUNT,
    MAX_SAMPLE_RECORDS,
    SAMPLE_STRATEGIES,
    SampleError,
    SampleSummary,
    peek,
    sample,
    sample_file,
)

__all__ = [
    "Record", "estimate_tokens",
    "Segmenter", "FormatSegmenter", "JsonLineSegmenter", "RegexSegmenter", "RawTextSegmenter",
    "build_segmenter", "detect_segmenter_kind", "available_segmenters",
    "register_segmenter", "register_format", "register_segmenter_detector",
    "Source", "SourceError", "SourceResolution", "StaticFileSource", "LiveSource", "ArchiveSource",
    "build_source", "resolve_paths", "resolve_source_spec",
    "register_source_provider", "available_source_providers",
    "PLUGIN_API_VERSION", "PluginAPI", "load_entrypoint_plugins", "loaded_plugins",
    "AnalysisEvent", "EventRef", "EventTransformContext", "EventTransformError",
    "events_from_filter_result", "write_events_jsonl",
    "register_event_transformer", "available_event_transformers", "apply_event_transformers",
    "AnalysisRun", "RunFile", "RunWorkspace", "RunIntegrityError", "verify_manifest", "RUN_SCHEMA_VERSION",
    "FilterError", "FilterResult", "filter_text", "filter_texts",
    "pattern_from_terms", "parse_time_arg", "record_timestamp", "reference_datetime",
    "text_time_range", "top_terms_in_text",
    "PatternComponent", "coerce_pattern_components",
    "SurveyError", "SurveySummary", "survey", "survey_file",
    "SampleError", "SampleSummary", "sample", "sample_file", "peek",
    "DEFAULT_SAMPLE_CHARS", "DEFAULT_SAMPLE_COUNT", "MAX_SAMPLE_CHARS",
    "MAX_SAMPLE_COUNT", "MAX_SAMPLE_RECORDS", "SAMPLE_STRATEGIES",
]
