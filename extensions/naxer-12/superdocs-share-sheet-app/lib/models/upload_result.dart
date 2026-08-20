class UploadResult {
  final String sessionId;
  final String html;
  final String filename;
  final int? chunksCount;
  final String? versionId;

  UploadResult({
    required this.sessionId,
    required this.html,
    required this.filename,
    this.chunksCount,
    this.versionId,
  });

  factory UploadResult.fromJson(Map<String, dynamic> json) {
    return UploadResult(
      sessionId: json['session_id'] as String? ?? '',
      html: json['html'] as String? ?? '',
      filename: json['filename'] as String? ?? 'document',
      chunksCount: json['chunks_count'] as int?,
      versionId: json['version_id'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'session_id': sessionId,
      'html': html,
      'filename': filename,
      'chunks_count': chunksCount,
      'version_id': versionId,
    };
  }
}
