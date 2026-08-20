import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superdocs_share_sheet_app/api/superdocs_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({
      'superdocs_api_key': 'test_key_123',
    });
  });

  group('SuperDocsClient Unit Tests', () {
    test('uploadDocument generates and sends a session_id, sends file_base64', () async {
      // Verified live against the real API (2026-08-17): a real
      // upload-base64 call with no session_id does NOT persist and returns
      // no usable session_id at all -- the client must always generate and
      // send one itself. Also verified the real request field is
      // file_base64, not document_html.
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/v1/documents/upload-base64');
        expect(request.method, 'POST');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['return_html'], true);
        expect(body['filename'], 'test.docx');
        expect(body['file_base64'], isNotEmpty);
        expect(body['session_id'], isNotNull);
        expect(body['session_id'], isNotEmpty);

        return http.Response(
          jsonEncode({
            'session_id': body['session_id'],
            'html': '<p>Test Document</p>',
            'filename': 'test.docx',
            'chunks_count': 5,
            'persisted': true,
          }),
          200,
        );
      });

      final client = SuperDocsClient(
        httpClient: mockClient,
        baseUrl: 'https://api.superdocs.app',
      );

      final result = await client.uploadDocument(
        fileBytes: [10, 20, 30],
        filename: 'test.docx',
      );

      // session_id is client-generated (a UUID) -- assert shape, not a
      // fixed value, since a real client-supplied session_id is echoed
      // straight back by the real API.
      expect(result.sessionId, isNotEmpty);
      expect(result.html, '<p>Test Document</p>');
      expect(result.chunksCount, 5);
    });

    test('startEdit posts session_id and message', () async {
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/v1/chat/async');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['session_id'], 'sess_123');
        expect(body['message'], 'Make paragraph 1 concise');

        return http.Response(
          jsonEncode({
            'job_id': 'job_999',
            'session_id': 'sess_123',
            'status': 'pending',
          }),
          200,
        );
      });

      final client = SuperDocsClient(httpClient: mockClient);
      final result = await client.startEdit(
        sessionId: 'sess_123',
        instruction: 'Make paragraph 1 concise',
      );

      expect(result.jobId, 'job_999');
      expect(result.status, 'pending');
    });

    test('getJobStatus parses status and updated html diffs', () async {
      // Real shape, verified live against the real API (2026-08-17):
      // document_changes is nested under "result", not top-level.
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/v1/jobs/job_999');
        return http.Response(
          jsonEncode({
            'status': 'awaiting_approval',
            'result': {
              'document_changes': {
                'updated_html': '<h1>Updated Heading</h1>',
                'chunk_diffs': [
                  {'chunk_id': 'c1', 'action': 'update', 'content': 'Updated Heading'}
                ]
              }
            }
          }),
          200,
        );
      });

      final client = SuperDocsClient(httpClient: mockClient);
      final result = await client.getJobStatus(jobId: 'job_999');

      expect(result.status, 'awaiting_approval');
      expect(result.updatedHtml, '<h1>Updated Heading</h1>');
      expect(result.changedChunkIds, contains('c1'));
    });

    test('approve sends job_id and approval flag', () async {
      // job_id is required by the real ApprovalRequest schema, verified
      // live (2026-08-17) -- a request without it 422s for real.
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/v1/chat/sess_123/approve');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['job_id'], 'job_999');
        expect(body['approved'], true);
        return http.Response(jsonEncode({'status': 'approved'}), 200);
      });

      final client = SuperDocsClient(httpClient: mockClient);
      await expectLater(
        client.approve(sessionId: 'sess_123', jobId: 'job_999', approved: true),
        completes,
      );
    });

    test('export parses filename from Content-Disposition with both filename forms', () async {
      // Real header carries both forms on one line, verified live
      // (2026-08-17): filename="..." AND filename*=UTF-8''... together. A
      // naive split on "filename=" corrupts the parsed name by picking up
      // the second form's junk too -- this exercises that exact case.
      final mockClient = MockClient((request) async {
        expect(request.url.path, '/v1/documents/export');
        return http.Response.bytes(
          [80, 75, 3, 4],
          200,
          headers: {
            'content-disposition':
                'attachment; filename="edited.docx"; filename*=UTF-8\'\'edited.docx',
          },
        );
      });

      final client = SuperDocsClient(httpClient: mockClient);
      final result = await client.export(sessionId: 'sess_123', format: 'docx');

      expect(result.fileBytes, [80, 75, 3, 4]);
      expect(result.filename, 'edited.docx');
    });
  });
}
