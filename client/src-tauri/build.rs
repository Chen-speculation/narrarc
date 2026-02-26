fn main() {
  // Pass TARGET to lib.rs - Cargo sets TARGET in build scripts but not always at compile time
  println!("cargo:rustc-env=APP_TARGET={}", std::env::var("TARGET").unwrap_or_else(|_| "unknown".into()));
  tauri_build::build()
}
