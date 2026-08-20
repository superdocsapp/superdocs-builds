import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import '../api/superdocs_client.dart';
import '../models/edit_job.dart';
import '../storage/job_queue.dart';

// Valid minimal PKZip DOCX byte structure containing valid Word XML
final List<int> kValidSampleDocxBytes = [
  80, 75, 3, 4, 20, 0, 0, 0, 8, 0, 179, 113, 10, 93, 204, 84, 140, 16, 224, 0, 0, 0, 156, 1, 0, 0, 19, 0, 0, 0, 91, 67, 111, 110, 116, 101, 110, 116, 95, 84, 121, 112, 101, 115, 93, 46, 120, 109, 108, 125, 144, 203, 78, 195, 48, 16, 69, 127, 197, 242, 22, 197, 19, 186, 64, 8, 37, 233, 2, 202, 18, 88, 148, 15, 176, 236, 73, 98, 225, 151, 60, 110, 41, 127, 207, 164, 45, 93, 160, 194, 210, 190, 143, 51, 186, 221, 250, 16, 188, 216, 99, 33, 151, 98, 47, 111, 85, 43, 5, 70, 147, 172, 139, 83, 47, 223, 183, 207, 205, 189, 92, 15, 221, 246, 43, 35, 9, 182, 70, 234, 229, 92, 107, 126, 0, 32, 51, 99, 208, 164, 82, 198, 200, 202, 152, 74, 208, 149, 159, 101, 130, 172, 205, 135, 158, 16, 86, 109, 123, 7, 38, 197, 138, 177, 54, 117, 233, 144, 67, 247, 132, 163, 222, 249, 42, 54, 7, 254, 62, 97, 11, 122, 146, 226, 241, 100, 92, 88, 189, 212, 57, 123, 103, 116, 101, 29, 246, 209, 254, 162, 52, 103, 130, 226, 228, 209, 67, 179, 203, 116, 195, 6, 9, 87, 9, 139, 242, 55, 224, 156, 123, 229, 29, 138, 179, 40, 222, 116, 169, 47, 58, 176, 11, 62, 83, 177, 96, 147, 217, 5, 78, 170, 255, 107, 174, 220, 153, 198, 209, 25, 188, 228, 151, 182, 92, 146, 65, 34, 30, 56, 120, 117, 81, 130, 118, 241, 231, 126, 56, 206, 61, 124, 3, 80, 75, 3, 4, 20, 0, 0, 0, 8, 0, 179, 113, 10, 93, 54, 87, 222, 220, 162, 0, 0, 0, 24, 1, 0, 0, 11, 0, 0, 0, 95, 114, 101, 108, 115, 47, 46, 114, 101, 108, 115, 141, 207, 59, 14, 194, 48, 12, 6, 224, 171, 68, 222, 169, 11, 3, 66, 168, 105, 23, 132, 212, 21, 149, 3, 68, 137, 155, 70, 52, 15, 37, 225, 117, 123, 50, 48, 80, 196, 192, 104, 251, 247, 103, 185, 233, 30, 118, 102, 55, 138, 201, 120, 199, 97, 93, 213, 192, 200, 73, 175, 140, 211, 28, 206, 195, 113, 181, 131, 174, 109, 78, 52, 139, 92, 18, 105, 50, 33, 177, 178, 226, 18, 135, 41, 231, 176, 71, 76, 114, 34, 43, 82, 229, 3, 185, 50, 25, 125, 180, 34, 151, 50, 106, 12, 62, 94, 132, 38, 220, 212, 245, 22, 227, 167, 1, 75, 147, 245, 138, 67, 236, 213, 26, 216, 240, 12, 244, 143, 237, 199, 209, 72, 58, 120, 121, 181, 228, 242, 143, 19, 95, 137, 34, 139, 168, 41, 115, 184, 251, 168, 80, 189, 219, 85, 97, 1, 219, 6, 23, 47, 182, 47, 80, 75, 3, 4, 20, 0, 0, 0, 8, 0, 179, 113, 10, 93, 11, 225, 205, 44, 231, 0, 0, 0, 94, 1, 0, 0, 17, 0, 0, 0, 119, 111, 114, 100, 47, 100, 111, 99, 117, 109, 101, 110, 116, 46, 120, 109, 108, 109, 144, 219, 106, 195, 48, 12, 134, 95, 69, 248, 126, 113, 154, 177, 49, 66, 154, 222, 148, 222, 236, 102, 163, 221, 3, 184, 142, 18, 27, 98, 203, 200, 78, 179, 188, 253, 236, 177, 3, 140, 129, 248, 133, 144, 244, 233, 208, 29, 222, 221, 12, 55, 228, 104, 201, 239, 197, 174, 170, 5, 160, 215, 52, 88, 63, 237, 197, 219, 229, 116, 247, 36, 14, 125, 183, 182, 3, 233, 197, 161, 79, 144, 235, 125, 108, 215, 189, 48, 41, 133, 86, 202, 168, 13, 58, 21, 43, 10, 232, 115, 110, 36, 118, 42, 229, 144, 39, 185, 18, 15, 129, 73, 99, 140, 25, 231, 102, 217, 212, 245, 163, 116, 202, 122, 81, 144, 87, 26, 182, 226, 67, 17, 46, 146, 250, 243, 18, 144, 143, 164, 35, 156, 149, 11, 51, 194, 241, 107, 110, 5, 23, 99, 35, 100, 11, 138, 213, 196, 42, 24, 216, 1, 141, 144, 12, 2, 99, 32, 78, 85, 39, 11, 162, 40, 127, 106, 248, 75, 127, 249, 105, 109, 90, 120, 198, 13, 70, 235, 149, 215, 86, 205, 25, 113, 67, 191, 32, 76, 76, 107, 50, 96, 189, 102, 84, 17, 7, 184, 110, 208, 60, 64, 222, 74, 151, 235, 173, 135, 215, 251, 255, 6, 201, 239, 123, 228, 239, 175, 250, 15, 80, 75, 1, 2, 20, 3, 20, 0, 0, 0, 8, 0, 179, 113, 10, 93, 204, 84, 140, 16, 224, 0, 0, 0, 156, 1, 0, 0, 19, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 128, 1, 0, 0, 0, 0, 91, 67, 111, 110, 116, 101, 110, 116, 95, 84, 121, 112, 101, 115, 93, 46, 120, 109, 108, 80, 75, 1, 2, 20, 3, 20, 0, 0, 0, 8, 0, 179, 113, 10, 93, 54, 87, 222, 220, 162, 0, 0, 0, 24, 1, 0, 0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 128, 1, 17, 1, 0, 0, 95, 114, 101, 108, 115, 47, 46, 114, 101, 108, 115, 80, 75, 1, 2, 20, 3, 20, 0, 0, 0, 8, 0, 179, 113, 10, 93, 11, 225, 205, 44, 231, 0, 0, 0, 94, 1, 0, 0, 17, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 128, 1, 220, 1, 0, 0, 119, 111, 114, 100, 47, 100, 111, 99, 117, 109, 101, 110, 116, 46, 120, 109, 108, 80, 75, 5, 6, 0, 0, 0, 0, 3, 0, 3, 0, 185, 0, 0, 0, 242, 2, 0, 0, 0, 0
];

class InstructionScreen extends StatefulWidget {
  const InstructionScreen({super.key});

  @override
  State<InstructionScreen> createState() => _InstructionScreenState();
}

class _InstructionScreenState extends State<InstructionScreen> {
  final _instructionController = TextEditingController();
  final _client = SuperDocsClient();
  final _jobQueue = JobQueue();

  bool _isSubmitting = false;
  String _filename = 'document.docx';
  List<int> _fileBytes = kValidSampleDocxBytes;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final args = ModalRoute.of(context)?.settings.arguments;
    if (args is Map<String, dynamic>) {
      if (args.containsKey('filename')) {
        _filename = args['filename'] as String;
      }
      if (args.containsKey('fileBytes') && args['fileBytes'] is List<int>) {
        _fileBytes = args['fileBytes'] as List<int>;
      } else if (args.containsKey('filePath') && args['filePath'] is String) {
        final path = args['filePath'] as String;
        try {
          final file = File(path);
          if (file.existsSync()) {
            _fileBytes = file.readAsBytesSync();
          }
        } catch (_) {}
      }
    }
  }

  Future<void> _submitInstruction() async {
    final instruction = _instructionController.text.trim();
    if (instruction.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter an instruction for the AI editor')),
      );
      return;
    }

    FocusScope.of(context).unfocus();
    setState(() => _isSubmitting = true);

    try {
      // 1. Upload document (sending valid PKZip DOCX bytes to SuperDocs API)
      final uploadRes = await _client.uploadDocument(
        fileBytes: _fileBytes,
        filename: _filename,
      );

      // 2. Start edit
      final chatRes = await _client.startEdit(
        sessionId: uploadRes.sessionId,
        instruction: instruction,
      );

      // 3. Persist job locally
      final newJob = EditJob(
        jobId: chatRes.jobId,
        sessionId: uploadRes.sessionId,
        filename: _filename,
        status: chatRes.status,
        createdAt: DateTime.now(),
        instruction: instruction,
      );
      await _jobQueue.addJob(newJob);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Edit job started! Processing in background.')),
        );
        Navigator.of(context).pushReplacementNamed('/home');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error starting edit: $e'),
            duration: const Duration(seconds: 5),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => FocusScope.of(context).unfocus(),
      child: Scaffold(
        backgroundColor: const Color(0xFF0F172A),
        resizeToAvoidBottomInset: true,
        appBar: AppBar(
          backgroundColor: const Color(0xFF0F172A),
          elevation: 0,
          title: const Text(
            'Edit Instruction',
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
          ),
          actions: [
            IconButton(
              icon: const Icon(Icons.keyboard_hide_rounded, color: Color(0xFF94A3B8)),
              tooltip: 'Dismiss Keyboard',
              onPressed: () => FocusScope.of(context).unfocus(),
            ),
          ],
        ),
        body: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) {
              return SingleChildScrollView(
                padding: const EdgeInsets.all(24.0),
                child: ConstrainedBox(
                  constraints: BoxConstraints(minHeight: constraints.maxHeight - 48),
                  child: IntrinsicHeight(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            color: const Color(0xFF1E293B),
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(color: const Color(0xFF334155)),
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.file_present_rounded, color: Colors.blueAccent, size: 28),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    const Text(
                                      'Selected File',
                                      style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
                                    ),
                                    Text(
                                      _filename,
                                      style: const TextStyle(
                                        color: Colors.white,
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 24),
                        const Text(
                          'What edit would you like to make?',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        const SizedBox(height: 8),
                        const Text(
                          'Describe the changes in plain language or dictate via your keyboard microphone.',
                          style: TextStyle(color: Color(0xFF94A3B8), fontSize: 14),
                        ),
                        const SizedBox(height: 16),
                        TextField(
                          controller: _instructionController,
                          minLines: 4,
                          maxLines: 8,
                          style: const TextStyle(color: Colors.white, fontSize: 16),
                          decoration: InputDecoration(
                            hintText: 'e.g. Update paragraph 2 to summarize key metrics and highlight revenue growth.',
                            hintStyle: const TextStyle(color: Color(0xFF64748B)),
                            filled: true,
                            fillColor: const Color(0xFF1E293B),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(16),
                              borderSide: BorderSide.none,
                            ),
                            contentPadding: const EdgeInsets.all(16),
                          ),
                        ),
                        const Spacer(),
                        const SizedBox(height: 16),
                        SizedBox(
                          width: double.infinity,
                          height: 54,
                          child: ElevatedButton(
                            onPressed: _isSubmitting ? null : _submitInstruction,
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.blueAccent,
                              foregroundColor: Colors.white,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(14),
                              ),
                              elevation: 0,
                            ),
                            child: _isSubmitting
                                ? const CircularProgressIndicator(color: Colors.white)
                                : const Row(
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                      Icon(Icons.send_rounded, size: 20),
                                      SizedBox(width: 8),
                                      Text(
                                        'Go',
                                        style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                                      ),
                                    ],
                                  ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}
