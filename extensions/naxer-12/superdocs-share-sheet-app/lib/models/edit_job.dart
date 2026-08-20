class EditJob {
  final String jobId;
  final String sessionId;
  final String filename;
  final String status;
  final DateTime createdAt;
  final String? instruction;
  final String? updatedHtml;

  EditJob({
    required this.jobId,
    required this.sessionId,
    required this.filename,
    required this.status,
    required this.createdAt,
    this.instruction,
    this.updatedHtml,
  });

  factory EditJob.fromJson(Map<String, dynamic> json) {
    return EditJob(
      jobId: json['jobId'] as String? ?? json['job_id'] as String? ?? '',
      sessionId: json['sessionId'] as String? ?? json['session_id'] as String? ?? '',
      filename: json['filename'] as String? ?? 'document',
      status: json['status'] as String? ?? 'pending',
      createdAt: json['createdAt'] != null
          ? DateTime.parse(json['createdAt'] as String)
          : DateTime.now(),
      instruction: json['instruction'] as String?,
      updatedHtml: json['updatedHtml'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'jobId': jobId,
      'sessionId': sessionId,
      'filename': filename,
      'status': status,
      'createdAt': createdAt.toIso8601String(),
      'instruction': instruction,
      'updatedHtml': updatedHtml,
    };
  }

  EditJob copyWith({
    String? jobId,
    String? sessionId,
    String? filename,
    String? status,
    DateTime? createdAt,
    String? instruction,
    String? updatedHtml,
  }) {
    return EditJob(
      jobId: jobId ?? this.jobId,
      sessionId: sessionId ?? this.sessionId,
      filename: filename ?? this.filename,
      status: status ?? this.status,
      createdAt: createdAt ?? this.createdAt,
      instruction: instruction ?? this.instruction,
      updatedHtml: updatedHtml ?? this.updatedHtml,
    );
  }
}
