import 'dart:convert';

class ChunkDiff {
  final String chunkId;
  final String action;
  final String content;

  ChunkDiff({
    required this.chunkId,
    required this.action,
    required this.content,
  });

  factory ChunkDiff.fromJson(Map<String, dynamic> json) {
    return ChunkDiff(
      chunkId: json['chunk_id'] as String? ?? json['id'] as String? ?? '',
      action: json['action'] as String? ?? 'update',
      content: json['content'] as String? ?? '',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'chunk_id': chunkId,
      'action': action,
      'content': content,
    };
  }
}

class JobStatusResult {
  final String status;
  final String? updatedHtml;
  final List<ChunkDiff>? diffs;
  final List<String>? changedChunkIds;
  final String? rawResponse;

  JobStatusResult({
    required this.status,
    this.updatedHtml,
    this.diffs,
    this.changedChunkIds,
    this.rawResponse,
  });

  factory JobStatusResult.fromJson(Map<String, dynamic> json) {
    final status = json['status'] as String? ?? 'pending';
    String? html;
    List<ChunkDiff>? parsedDiffs;
    List<String>? chunkIds;

    // The real GET /v1/jobs/{job_id} response nests document_changes under
    // `result` (JobResult.document_changes), not at the top level -- verified
    // against the live OpenAPI spec (2026-08-17). The top-level fallback
    // below is kept defensively in case an older/alternate response shape
    // is ever encountered, but `result.document_changes` is the real path.
    final result = json['result'];
    final documentChanges = (result is Map<String, dynamic>)
        ? result['document_changes']
        : json['document_changes'];

    if (documentChanges != null) {
      dynamic changes = documentChanges;
      if (changes is String) {
        try {
          changes = jsonDecode(changes);
        } catch (_) {}
      }

      if (changes is Map<String, dynamic>) {
        html = changes['updated_html'] as String? ?? changes['html'] as String?;
        if (changes.containsKey('chunk_diffs') && changes['chunk_diffs'] is List) {
          final list = changes['chunk_diffs'] as List;
          parsedDiffs = list
              .whereType<Map<String, dynamic>>()
              .map((item) => ChunkDiff.fromJson(item))
              .toList();
          chunkIds = parsedDiffs.map((d) => d.chunkId).where((id) => id.isNotEmpty).toList();
        }
      }
    } else if (json.containsKey('updated_html')) {
      html = json['updated_html'] as String?;
    }

    return JobStatusResult(
      status: status,
      updatedHtml: html,
      diffs: parsedDiffs,
      changedChunkIds: chunkIds,
      rawResponse: jsonEncode(json),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'status': status,
      'updated_html': updatedHtml,
      'changed_chunk_ids': changedChunkIds,
    };
  }
}
