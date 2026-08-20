import 'dart:async';
import 'package:flutter/material.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'app.dart';
import 'background/background_service.dart';
import 'storage/api_key_store.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize background WorkManager & local notifications
  try {
    await BackgroundService.initialize();
    await BackgroundService.registerPeriodicPoll();
  } catch (_) {}

  // Check stored API Key
  final keyStore = ApiKeyStore();
  final apiKey = await keyStore.getApiKey();
  final initialRoute = (apiKey == null || apiKey.isEmpty) ? '/onboarding' : '/home';

  // ShareIntentHandler was previously defined but never actually used --
  // runApp() built the bare SuperDocsApp, so a real shared file never
  // navigated anywhere. Found as a real, silent bug (2026-08-17): the
  // share-intake feature this whole app exists for was dead code.
  runApp(ShareIntentHandler(child: SuperDocsApp(initialRoute: initialRoute)));
}

class ShareIntentHandler extends StatefulWidget {
  final Widget child;
  const ShareIntentHandler({super.key, required this.child});

  @override
  State<ShareIntentHandler> createState() => _ShareIntentHandlerState();
}

class _ShareIntentHandlerState extends State<ShareIntentHandler> {
  late StreamSubscription _intentSubscription;

  @override
  void initState() {
    super.initState();
    // Listen for shared media/files while app is in memory
    _intentSubscription = ReceiveSharingIntent.instance.getMediaStream().listen(
      (List<SharedMediaFile> value) {
        if (value.isNotEmpty) {
          _handleSharedFile(value.first);
        }
      },
    );

    // Get shared media/files when app opened from closed state. Deferred to
    // after the first frame: this widget sits above MaterialApp, so on a
    // cold start the Navigator behind navigatorKey may not exist yet the
    // instant this Future resolves.
    ReceiveSharingIntent.instance.getInitialMedia().then(
      (List<SharedMediaFile> value) {
        if (value.isNotEmpty) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            _handleSharedFile(value.first);
          });
        }
      },
    );
  }

  void _handleSharedFile(SharedMediaFile file) {
    final path = file.path;
    final filename = path.split('/').last;

    // Navigate via the app-wide navigatorKey, not Navigator.of(context):
    // this widget wraps MaterialApp, so it has no Navigator ancestor of its
    // own to call Navigator.of(context) on.
    SuperDocsApp.navigatorKey.currentState?.pushNamed(
      '/instruction',
      arguments: {
        'filename': filename,
        'filePath': path,
      },
    );
  }

  @override
  void dispose() {
    _intentSubscription.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return widget.child;
  }
}
