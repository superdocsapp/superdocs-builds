class ChatJobResult {
  final String jobId;
  final String sessionId;
  final String status;

  ChatJobResult({
    required this.jobId,
    required this.sessionId,
    required this.status,
  });

  factory ChatJobResult.fromJson(Map<String, dynamic> json) {
    return ChatJobResult(
      jobId: json['job_id'] as String? ?? '',
      sessionId: json['session_id'] as String? ?? '',
      status: json['status'] as String? ?? 'pending',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'job_id': jobId,
      'session_id': sessionId,
      'status': status,
    };
  }
}
