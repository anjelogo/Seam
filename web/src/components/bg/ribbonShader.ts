export const vertexShader = /* glsl */ `
varying vec2 vUv;

void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

export const fragmentShader = /* glsl */ `
uniform float time;
uniform float speed;
uniform float glowPulse;
uniform float surge;
uniform vec3 stops[3];
uniform vec2 resolution;
uniform float dpr;

varying vec2 vUv;

const float TAU = 6.283185307;
const float SPAN = 1200.0;
const float ROWS = 800.0;
const float LINE_STEP = 0.09;
const float CORE_HALF_WIDTH = 0.525;
const float GLOW_SIGMA = 2.5;
const float GLOW_PEAK = 0.45;
const float GLOW_REACH = 12.0;
const float FAST_BOOST = 0.15;
// css 170deg: (sin, -cos) with y down
const vec2 GRADIENT_DIR = vec2(0.173648178, 0.984807753);

float ribbon(vec2 p, float n, float base, float amp, float phase, float spread, float offset, vec3 fade) {
  float unit = resolution.y / ROWS;
  float t = TAU * (p.x / resolution.x + offset / SPAN);
  float wave = 0.22 * amp * sin(2.0 * t + 1.7 * phase);
  float reach = (amp + (n * 0.5 - 1.0) * spread) * unit + GLOW_REACH;
  if (abs(p.y - (base + wave) * unit) > reach) return 0.0;

  float waveSlope = 0.44 * amp * cos(2.0 * t + 1.7 * phase);
  float slopeScale = TAU * unit / resolution.x;
  float s = sin(t + phase);
  float c = cos(t + phase);
  float stepSin = sin(LINE_STEP);
  float stepCos = cos(LINE_STEP);
  float center = (n - 1.0) * 0.5;
  float sum = 0.0;

  for (int i = 0; i < 16; i++) {
    float fi = float(i);
    if (fi >= n) break;
    float a = amp + (fi - n * 0.5) * spread;
    float slope = slopeScale * (c * a + waveSlope);
    float d = abs(p.y - (base + s * a + wave) * unit) * inversesqrt(1.0 + slope * slope);
    float core = clamp((CORE_HALF_WIDTH - d) * dpr + 0.5, 0.0, 1.0);
    float glow = GLOW_PEAK * exp(-0.5 * d * d / (GLOW_SIGMA * GLOW_SIGMA));
    float u = abs(fi - center) / center;
    float opacity = u < 0.5 ? mix(fade.x, fade.y, u * 2.0) : mix(fade.y, fade.z, u * 2.0 - 1.0);
    sum += opacity * (core + glow * (1.0 - core));

    float next = s * stepCos + c * stepSin;
    c = c * stepCos - s * stepSin;
    s = next;
  }
  return sum;
}

void main() {
  vec2 p = vec2(vUv.x, 1.0 - vUv.y) * resolution;

  float span = abs(resolution.x * GRADIENT_DIR.x) + abs(resolution.y * GRADIENT_DIR.y);
  float g = clamp(dot(p - 0.5 * resolution, GRADIENT_DIR) / span + 0.5, 0.0, 1.0);
  vec3 color = g < 0.55
    ? mix(stops[0], stops[1], g / 0.55)
    : mix(stops[1], stops[2], (g - 0.55) / 0.45);

  vec2 e = (p - resolution * vec2(0.5, 0.62)) / (resolution * vec2(0.7, 0.5));
  color = mix(color, vec3(1.0), 0.2 * glowPulse * (1.0 - smoothstep(0.0, 1.0, length(e))));

  float lines = ribbon(p, 16.0, 440.0, 95.0, 0.0, 3.0, SPAN * fract(time / 26.0) + surge, vec3(0.55, 0.26, 0.10))
    + ribbon(p, 10.0, 520.0, 60.0, 2.2, 4.0, SPAN * fract(time / 40.0) + surge, vec3(0.36, 0.18, 0.08));
  color += lines * (1.0 + FAST_BOOST * (speed - 1.0) / 7.0);

  // dither against gradient banding
  color += (fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715)))) - 0.5) / 255.0;
  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`;
