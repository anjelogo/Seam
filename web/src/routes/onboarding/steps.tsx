import type { PillOption } from "../../components/ui";
import type { TopSize } from "../../lib/viewmodel";
import { Silhouette } from "./Silhouette";

export const STEPS = [
  {
    question: "how tall are you?",
    tip: "sets your avatar's height so lengths and hems sit right.",
  },
  {
    question: "what do you weigh?",
    tip: "only used to shape your avatar. never shown to anyone.",
  },
  {
    question: "pick a body base.",
    tip: "a starting shape. you can fine-tune every proportion later.",
  },
  {
    question: "choose a skin tone.",
    tip: "so colors read the way they would on you.",
  },
  {
    question: "what size do you usually wear up top?",
    tip: "helps us flag listings that will actually fit.",
  },
  {
    question: "what style do you want to build today?",
    tip: "describe a vibe, a place, a person, an era. we pull thrift pieces that match and dress your avatar.",
  },
] as const;

export const BASE_OPTIONS: PillOption[] = [
  { value: "masc", label: "masculine", content: <Silhouette base="masc" /> },
  { value: "fem", label: "feminine", content: <Silhouette base="fem" /> },
];

const SKIN_TONES = ["#F6D9C6", "#EBC1A0", "#D9A57E", "#B9805A", "#93603F", "#6E452C", "#4A2E1F", "#2E1C13"];

export const SKIN_OPTIONS: PillOption[] = SKIN_TONES.map((hex, index) => ({
  value: hex,
  label: `tone ${index + 1}`,
  swatch: hex,
}));

const TOP_SIZES: TopSize[] = ["XS", "S", "M", "L", "XL", "XXL"];

export const SIZE_OPTIONS: PillOption[] = TOP_SIZES.map((size) => ({ value: size, label: size.toLowerCase() }));
