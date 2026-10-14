using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine;

namespace Vrar.EditorTools
{
    /// <summary>
    /// Headless smoke test: opens the PoC scene, enters play mode, waits for the
    /// telemetry client to land a few frames, then captures a screenshot and
    /// quits. Proves the scene renders and the avatars are being driven without a
    /// human at the Editor.
    ///
    /// Unity -batchmode -projectPath . \
    ///   -executeMethod Vrar.EditorTools.PocCapture.CaptureFromCommandLine \
    ///   -vrar-capture-out &lt;path.png&gt; -vrar-capture-frames 240
    /// </summary>
    public static class PocCapture
    {
        private const int DefaultFrames = 240;

        [MenuItem("VRAR/PoC/Capture Screenshot")]
        public static void CaptureFromMenu()
        {
            Capture("Artifacts/poc.png", DefaultFrames);
        }

        public static void CaptureFromCommandLine()
        {
            string output = ReadArgument("-vrar-capture-out") ?? "Artifacts/poc.png";
            int frames = int.TryParse(ReadArgument("-vrar-capture-frames"), out int parsed) ? parsed : DefaultFrames;
            Capture(output, frames);
        }

        public static void Capture(string outputPath, int frames)
        {
            if (!File.Exists(MvpSceneBuilder.ScenePath))
            {
                Debug.LogError($"[VRAR] scene missing: {MvpSceneBuilder.ScenePath}. Run VRAR/PoC/Build MVP Scene first.");
                EditorApplication.Exit(2);
                return;
            }

            EditorSceneManager.OpenScene(MvpSceneBuilder.ScenePath);

            // After opening, before play mode: the viewer only exists once the
            // scene is loaded, and the rig adopts this view on its first Awake.
            ApplyCaptureView();

            Debug.Log($"[VRAR] capturing after {frames} frames to {outputPath}");
            EditorApplication.EnterPlaymode();

            int warmup = frames;
            string absolute = Path.GetFullPath(outputPath);

            EditorApplication.CallbackFunction tick = null;
            tick = () =>
            {
                if (!EditorApplication.isPlaying)
                {
                    return;
                }

                if (warmup > 0)
                {
                    warmup--;
                    return;
                }

                EditorApplication.update -= tick;

                LogDiagnostics();
                Directory.CreateDirectory(Path.GetDirectoryName(absolute)!);

                // Prefer the real backbuffer: it reflects the actual render loop.
                // ScreenCapture is asynchronous, so stay alive until the file lands.
                ScreenCapture.CaptureScreenshot(absolute);
                double deadline = EditorApplication.timeSinceStartup + 10.0;
                EditorApplication.CallbackFunction wait = null;
                wait = () =>
                {
                    if (File.Exists(absolute) && new FileInfo(absolute).Length > 0)
                    {
                        EditorApplication.update -= wait;
                        Debug.Log($"[VRAR] screenshot written via ScreenCapture: {absolute}");
                        EditorApplication.Exit(0);
                        return;
                    }

                    if (EditorApplication.timeSinceStartup > deadline)
                    {
                        EditorApplication.update -= wait;
                        bool written = RenderToPng(Camera.main, absolute + ".fallback.png", 1600, 900);
                        Debug.Log($"[VRAR] fallback render written: {written}");
                        EditorApplication.Exit(written ? 0 : 3);
                    }
                };

                EditorApplication.update += wait;
            };

            EditorApplication.update += tick;
        }

        /// <summary>
        /// <c>-vrar-capture-view wide|nacelle</c>. The scene's default view frames
        /// the whole machine; the documentation shots of the avatars need the
        /// camera flown to the drive train first.
        /// </summary>
        private static void ApplyCaptureView()
        {
            string view = ReadArgument("-vrar-capture-view") ?? "wide";
            Presentation.SimulatedHmdRig viewer = Object.FindFirstObjectByType<Presentation.SimulatedHmdRig>();
            if (viewer == null)
            {
                return;
            }

            if (view == "nacelle")
            {
                MvpSceneBuilder.FrameViewerOnNacelle(viewer.gameObject);
            }
            else
            {
                MvpSceneBuilder.FrameViewer(viewer.gameObject, Camera.main);
            }

            Debug.Log($"[VRAR] capture view: {view} at {viewer.transform.position}");
        }

        /// <summary>Log what the PoC was actually showing when the frame was taken.</summary>
        private static void LogDiagnostics()
        {
            foreach (Presentation.SimulatedHmdRig viewer in Object.FindObjectsByType<Presentation.SimulatedHmdRig>())
            {
                Debug.Log($"[VRAR] viewer {viewer.name} at {viewer.transform.position} rot {viewer.transform.eulerAngles}");
            }

            Camera main = Camera.main;
            if (main != null)
            {
                Debug.Log($"[VRAR] camera {main.name} at {main.transform.position} fov={main.fieldOfView} " +
                          $"aspect={main.aspect:0.00} far={main.farClipPlane}");
            }

            foreach (Vrar.Bootstrap.MvpBootstrap bootstrap in Object.FindObjectsByType<Vrar.Bootstrap.MvpBootstrap>())
            {
                Vrar.Telemetry.TelemetryFrame frame = bootstrap.LastFrame;
                Debug.Log($"[VRAR] telemetry connected={bootstrap.Connected} endpoint={bootstrap.Endpoint} " +
                          $"frame={(frame == null ? "none" : $"t={frame.elapsed_s}s scenario={frame.scenario}")} " +
                          $"worstHealth={bootstrap.Rig?.WorstHealth():0.00}");
            }

            foreach (Light light in Object.FindObjectsByType<Light>())
            {
                Debug.Log($"[VRAR] light {light.name} intensity={light.intensity} enabled={light.enabled}");
            }
        }

        /// <summary>
        /// Render the active camera into a texture and write a PNG. ScreenCapture
        /// does not fire in batch mode, so the camera is rendered explicitly.
        /// </summary>
        private static bool RenderToPng(Camera camera, string path, int width, int height)
        {
            if (camera == null)
            {
                Debug.LogError("[VRAR] no camera found in the scene");
                return false;
            }

            var texture = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
            texture.antiAliasing = 2;
            RenderTexture previous = RenderTexture.active;
            RenderTexture previousTarget = camera.targetTexture;

            try
            {
                camera.targetTexture = texture;

                // URP sets up lighting per render pass; the legacy Camera.Render()
                // path leaves objects unlit. Ask the pipeline explicitly.
                var request = new UniversalRenderPipeline.SingleCameraRequest { destination = texture };
                if (RenderPipeline.SupportsRenderRequest(camera, request))
                {
                    RenderPipeline.SubmitRenderRequest(camera, request);
                }
                else
                {
                    camera.Render();
                }

                RenderTexture.active = texture;

                Texture2D image = new Texture2D(width, height, TextureFormat.RGB24, false);
                image.ReadPixels(new Rect(0f, 0f, width, height), 0, 0);
                image.Apply();

                Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllBytes(path, image.EncodeToPNG());
                Object.DestroyImmediate(image);
                return true;
            }
            catch (System.Exception exception)
            {
                Debug.LogError($"[VRAR] capture failed: {exception.Message}");
                return false;
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previous;
                Object.DestroyImmediate(texture);
            }
        }

        private static string ReadArgument(string name)
        {
            string[] arguments = System.Environment.GetCommandLineArgs();
            for (int i = 0; i < arguments.Length - 1; i++)
            {
                if (arguments[i] == name)
                {
                    return arguments[i + 1];
                }
            }

            return null;
        }
    }
}