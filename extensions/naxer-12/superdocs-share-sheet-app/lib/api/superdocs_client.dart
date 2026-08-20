import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';
import '../models/upload_result.dart';
import '../models/chat_job_result.dart';
import '../models/job_status_result.dart';
import '../models/export_result.dart';
import '../storage/api_key_store.dart';

class SuperDocsClient {
  final String baseUrl;
  final http.Client _httpClient;
  final ApiKeyStore _apiKeyStore;

  SuperDocsClient({
    this.baseUrl = 'https://api.superdocs.app',
    http.Client? httpClient,
    ApiKeyStore? apiKeyStore,
  })  : _httpClient = httpClient ?? http.Client(),
        _apiKeyStore = apiKeyStore ?? ApiKeyStore();

  Future<Map<String, String>> _getHeaders() async {
    final apiKey = await _apiKeyStore.getApiKey();
    return {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ${apiKey ?? ''}',
    };
  }

  Future<UploadResult> uploadDocument({
    required List<int> fileBytes,
    required String filename,
  }) async {
    final uri = Uri.parse('$baseUrl/v1/documents/upload-base64');
    final base64Content = base64Encode(fileBytes);
    final headers = await _getHeaders();

    // The real API does NOT auto-generate a session_id when one is omitted --
    // verified live against a real account (2026-08-17): omitting session_id
    // triggers the "one-off conversion" path, which returns no session_id at
    // all and does not persist the document (`"persisted": false`). Every
    // downstream call (startEdit, approve, export) needs a session_id, so the
    // client must generate one itself, matching the `^[a-zA-Z0-9_\-\.]+$`
    // pattern the real API's AsyncChatRequest.session_id requires.
    final sessionId = const Uuid().v4();

    final response = await _httpClient.post(
      uri,
      headers: headers,
      body: jsonEncode({
        'filename': filename,
        'file_base64': base64Content,
        'session_id': sessionId,
        'return_html': true,
      }),
    );

    if (response.statusCode >= 200 && response.statusCode < 300) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return UploadResult.fromJson({
        ...data,
        // The real response echoes session_id back, but fall back to the
        // one we generated in case a future API revision omits it again.
        'session_id': data['session_id'] ?? sessionId,
        'filename': data['filename'] ?? filename,
      });
    } else {
      throw Exception(
        'Upload failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }

  Future<ChatJobResult> startEdit({
    required String sessionId,
    required String instruction,
  }) async {
    final uri = Uri.parse('$baseUrl/v1/chat/async');
    final headers = await _getHeaders();

    final response = await _httpClient.post(
      uri,
      headers: headers,
      body: jsonEncode({
        'message': instruction,
        'session_id': sessionId,
      }),
    );

    if (response.statusCode >= 200 && response.statusCode < 300) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return ChatJobResult.fromJson(data);
    } else {
      throw Exception(
        'Start edit failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }

  Future<JobStatusResult> getJobStatus({required String jobId}) async {
    final uri = Uri.parse('$baseUrl/v1/jobs/$jobId');
    final headers = await _getHeaders();

    final response = await _httpClient.get(
      uri,
      headers: headers,
    );

    if (response.statusCode >= 200 && response.statusCode < 300) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return JobStatusResult.fromJson(data);
    } else {
      throw Exception(
        'Get job status failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }

  Future<void> approve({
    required String sessionId,
    required String jobId,
    required bool approved,
  }) async {
    final uri = Uri.parse('$baseUrl/v1/chat/$sessionId/approve');
    final headers = await _getHeaders();

    // job_id is required by the real ApprovalRequest schema, verified
    // against the live OpenAPI spec (2026-08-17) -- omitting it 422s. This
    // is whole-document approve/reject (v1 cut): job_id + approved only,
    // no change_id/changes, which the real API also supports for the
    // deferred v2 per-chunk approve/reject flow.
    final response = await _httpClient.post(
      uri,
      headers: headers,
      body: jsonEncode({
        'job_id': jobId,
        'approved': approved,
      }),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception(
        'Approve failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }

  Future<ExportResult> export({
    required String sessionId,
    required String format,
  }) async {
    final uri = Uri.parse('$baseUrl/v1/documents/export');
    final headers = await _getHeaders();

    final response = await _httpClient.post(
      uri,
      headers: headers,
      body: jsonEncode({
        'session_id': sessionId,
        'format': format,
      }),
    );

    if (response.statusCode >= 200 && response.statusCode < 300) {
      String filename = 'exported_document.$format';
      final disposition = response.headers['content-disposition'];
      if (disposition != null) {
        // The real header carries BOTH forms on one line, e.g.:
        //   attachment; filename="SuperDocs Document.docx"; filename*=UTF-8''SuperDocs%20Document.docx
        // verified live against the real export endpoint (2026-08-17). A
        // naive split on "filename=" captures everything after the first
        // match, including the trailing "; filename*=..." segment, which
        // corrupts the filename. Match only the quoted value.
        final match = RegExp(r'filename="([^"]+)"').firstMatch(disposition);
        if (match != null) {
          filename = match.group(1)!;
        }
      }

      return ExportResult(
        fileBytes: response.bodyBytes,
        filename: filename,
        contentType: response.headers['content-type'] ?? 'application/octet-stream',
      );
    } else {
      throw Exception(
        'Export failed with status ${response.statusCode}: ${response.body}',
      );
    }
  }
}
