import { Navbar } from "./components/Navbar";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { Comparison } from "./components/Comparison";
import { FinancialMemory } from "./components/FinancialMemory";
import { Features } from "./components/Features";
import { SmallBusiness } from "./components/SmallBusiness";
import { Trust } from "./components/Trust";
import { Vision } from "./components/Vision";
import { Testimonials } from "./components/Testimonials";
import { FinalCTA } from "./components/FinalCTA";
import { Footer } from "./components/Footer";

export default function App() {
  return (
    <div id="top" className="min-h-screen">
      <a
        href="#hero-demo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-brand-500 focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to demo
      </a>
      <Navbar />
      <main>
        <Hero />
        <HowItWorks />
        <Comparison />
        <FinancialMemory />
        <Features />
        <SmallBusiness />
        <Trust />
        <Vision />
        <Testimonials />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}
