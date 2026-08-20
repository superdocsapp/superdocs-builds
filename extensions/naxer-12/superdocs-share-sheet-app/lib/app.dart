import 'package:flutter/material.dart';
import 'screens/onboarding_screen.dart';
import 'screens/home_screen.dart';
import 'screens/instruction_screen.dart';
import 'screens/review_screen.dart';

class SuperDocsApp extends StatelessWidget {
  final String initialRoute;

  const SuperDocsApp({
    super.key,
    this.initialRoute = '/home',
  });

  // A widget above MaterialApp (main.dart's ShareIntentHandler, which needs
  // to navigate on a shared file even before any screen has built) has no
  // Navigator ancestor to call Navigator.of(context) on -- MaterialApp is
  // what creates the Navigator, and it's below that widget in the tree, not
  // above it. This key is the standard way to get a navigator reference
  // from outside the widget subtree MaterialApp owns. Found as a real,
  // silent bug (2026-08-17): ShareIntentHandler existed but was never
  // wrapped around the app at all, so no shared file ever navigated
  // anywhere -- fixed alongside adding this key.
  static final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
      title: 'SuperDocs Mobile',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0F172A),
        colorScheme: const ColorScheme.dark(
          primary: Colors.blueAccent,
          secondary: Color(0xFF10B981),
          surface: Color(0xFF1E293B),
        ),
        useMaterial3: true,
      ),
      initialRoute: initialRoute,
      routes: {
        '/onboarding': (context) => const OnboardingScreen(),
        '/home': (context) => const HomeScreen(),
        '/instruction': (context) => const InstructionScreen(),
        '/review': (context) => const ReviewScreen(),
      },
    );
  }
}
