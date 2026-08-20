import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../api/superdocs_client.dart';
import '../export/export_handler.dart';
import '../models/job_status_result.dart';
import '../storage/job_queue.dart';

class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key});

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  final _client = SuperDocsClient();
  final _jobQueue = JobQueue();
  final _exportHandler = ExportHandler();

  late final WebViewController _webViewController;
  bool _isLoading = true;
  bool _isProcessingAction = false;
  String _jobId = '';
  String _sessionId = '';
  String _filename = 'document.docx';
  JobStatusResult? _statusResult;

  @override
  void initState() {
    super.initState();
    _webViewController = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF0F172A));
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final args = ModalRoute.of(context)?.settings.arguments;
    if (args is Map<String, dynamic>) {
      _jobId = args['jobId'] as String? ?? '';
      _sessionId = args['sessionId'] as String? ?? '';
      _filename = args['filename'] as String? ?? 'edited_document.docx';
      if (_jobId.isNotEmpty) {
        _fetchStatusAndRender();
      }
    }
  }

  Future<void> _fetchStatusAndRender() async {
    setState(() => _isLoading = true);
    try {
      final res = await _client.getJobStatus(jobId: _jobId);
      _statusResult = res;

      final rawHtml = res.updatedHtml ??
          '<html><body><h3>No changes preview available.</h3></body></html>';

      // Inject viewport meta and highlight CSS
      final htmlContent = '''
<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 16px;
      margin: 0;
      background-color: #0f172a;
      color: #f8fafc;
      line-height: 1.6;
    }
    .diff-highlight, [data-chunk-id] {
      background-color: rgba(251, 191, 36, 0.25);
      border-left: 3px solid #fbbf24;
      padding: 4px 8px;
      margin: 4px 0;
      border-radius: 4px;
    }
    img { max-width: 100%; height: auto; }
    table { width: 100%; border-collapse: collapse; }
  </style>
</head>
<body>
  $rawHtml
</body>
</html>
''';

      await _webViewController.loadHtmlString(htmlContent);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error loading preview: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
      }
    }
  }

  Future<void> _handleApprove() async {
    setState(() => _isProcessingAction = true);
    try {
      // A job can go straight from pending to completed with no
      // awaiting_approval step (auto-approved) -- confirmed live on a real
      // device (2026-08-17): calling approve() on an already-completed job
      // returns a real 400 ("Job is not awaiting approval"). Only call
      // approve() when there's actually something pending approval.
      if (_statusResult?.status == 'awaiting_approval') {
        await _client.approve(sessionId: _sessionId, jobId: _jobId, approved: true);
      }
      await _jobQueue.updateJobStatus(_jobId, 'completed');

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Approved! Preparing document export...')),
        );
      }

      await _exportHandler.exportAndShare(
        sessionId: _sessionId,
        filename: _filename,
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Approval export error: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isProcessingAction = false);
      }
    }
  }

  Future<void> _handleReject() async {
    setState(() => _isProcessingAction = true);
    try {
      if (_statusResult?.status == 'completed') {
        // Same auto-approval case as _handleApprove -- an already-completed
        // edit was already applied server-side and can't be un-applied via
        // this endpoint. Reflect that honestly instead of sending a
        // rejection the real API will 400 on.
        await _jobQueue.updateJobStatus(_jobId, 'completed');
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'This edit was already applied automatically and cannot be rejected.',
              ),
            ),
          );
          Navigator.of(context).pushReplacementNamed('/home');
        }
        return;
      }

      await _client.approve(sessionId: _sessionId, jobId: _jobId, approved: false);
      await _jobQueue.updateJobStatus(_jobId, 'cancelled');

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Edit rejected.')),
        );
        Navigator.of(context).pushReplacementNamed('/home');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Rejection error: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isProcessingAction = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F172A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0F172A),
        elevation: 0,
        title: const Text(
          'Review Edits',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
        ),
      ),
      body: Stack(
        children: [
          Positioned.fill(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator(color: Colors.blueAccent))
                : WebViewWidget(controller: _webViewController),
          ),
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: const Color(0xFF1E293B),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.4),
                    blurRadius: 16,
                    offset: const Offset(0, -4),
                  ),
                ],
                borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
              ),
              child: SafeArea(
                top: false,
                child: Row(
                  children: [
                    Expanded(
                      child: SizedBox(
                        height: 52,
                        child: OutlinedButton(
                          onPressed: _isProcessingAction ? null : _handleReject,
                          style: OutlinedButton.styleFrom(
                            foregroundColor: Colors.redAccent,
                            side: const BorderSide(color: Colors.redAccent, width: 1.5),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14),
                            ),
                          ),
                          child: const Text(
                            'Reject',
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 16),
                    Expanded(
                      child: SizedBox(
                        height: 52,
                        child: ElevatedButton(
                          onPressed: _isProcessingAction ? null : _handleApprove,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFF10B981),
                            foregroundColor: Colors.white,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(14),
                            ),
                            elevation: 0,
                          ),
                          child: _isProcessingAction
                              ? const CircularProgressIndicator(color: Colors.white)
                              : const Text(
                                  'Approve',
                                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
