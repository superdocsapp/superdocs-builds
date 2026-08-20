import 'package:flutter/material.dart';
import '../models/edit_job.dart';
import '../storage/job_queue.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _jobQueue = JobQueue();
  List<EditJob> _jobs = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _refreshJobs();
  }

  Future<void> _refreshJobs() async {
    setState(() => _isLoading = true);
    final jobs = await _jobQueue.getJobs();
    setState(() {
      _jobs = jobs;
      _isLoading = false;
    });
  }

  Color _getStatusColor(String status) {
    switch (status.toLowerCase()) {
      case 'awaiting_approval':
        return Colors.amber;
      case 'completed':
        return const Color(0xFF10B981);
      case 'in_progress':
      case 'pending':
        return Colors.blueAccent;
      case 'failed':
      case 'cancelled':
      case 'rejected':
        return Colors.redAccent;
      default:
        return Colors.grey;
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
          'Document Edits',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, color: Color(0xFF94A3B8)),
            onPressed: _refreshJobs,
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined, color: Color(0xFF94A3B8)),
            onPressed: () => Navigator.of(context).pushNamed('/onboarding'),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: Colors.blueAccent))
          : _jobs.isEmpty
              ? _buildEmptyState()
              : RefreshIndicator(
                  onRefresh: _refreshJobs,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _jobs.length,
                    itemBuilder: (context, index) {
                      final job = _jobs[index];
                      return _buildJobCard(job);
                    },
                  ),
                ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {
          // This quick-action entry point has no real file picker wired in
          // yet -- that's share-intake's job, not this screen's. Passing
          // placeholder bytes here (previously [1, 2, 3, 4]) made every
          // real upload attempt fail with a real, confirmed 400 ("File is
          // not a zip file") -- found by actually running this on a device
          // (2026-08-17). Omitting `fileBytes` lets instruction_screen's
          // own valid embedded sample DOCX (kValidSampleDocxBytes) be used
          // instead, so this demo entry point produces a real, uploadable
          // file until a real picker replaces it.
          Navigator.of(context).pushNamed(
            '/instruction',
            arguments: {
              'filename': 'sample_document.docx',
            },
          );
        },
        backgroundColor: Colors.blueAccent,
        icon: const Icon(Icons.add_rounded, color: Colors.white),
        label: const Text(
          'New Edit',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.description_outlined, size: 64, color: Color(0xFF64748B)),
            const SizedBox(height: 16),
            const Text(
              'No Edits Yet',
              style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            const Text(
              'Share a file from Files or Mail into SuperDocs, or tap New Edit below to start.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Color(0xFF94A3B8), fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildJobCard(EditJob job) {
    final statusColor = _getStatusColor(job.status);

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      color: const Color(0xFF1E293B),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: statusColor.withOpacity(0.15),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Icon(Icons.insert_drive_file_outlined, color: statusColor),
        ),
        title: Text(
          job.filename,
          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 4),
            Text(
              job.instruction ?? 'Edit requested',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 13),
            ),
            const SizedBox(height: 6),
            Row(
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: statusColor,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  job.status.toUpperCase(),
                  style: TextStyle(
                    color: statusColor,
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
          ],
        ),
        trailing: const Icon(Icons.chevron_right_rounded, color: Color(0xFF64748B)),
        onTap: () {
          Navigator.of(context).pushNamed(
            '/review',
            arguments: {
              'jobId': job.jobId,
              'sessionId': job.sessionId,
            },
          );
        },
      ),
    );
  }
}
