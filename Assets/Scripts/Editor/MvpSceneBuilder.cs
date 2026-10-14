using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using Vrar.Bootstrap;
using Vrar.Presentation;
using Vrar.Turbine;

namespace Vrar.EditorTools
{
    /// <summary>
    /// Generates the PoC scene from code so the repository carries no binary
    /// scene diffs and CI can rebuild it headlessly:
    /// <c>Unity -batchmode -executeMethod Vrar.EditorTools.MvpSceneBuilder.BuildFromCommandLine</c>
    /// </summary>
    public static class MvpSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/Mvp/Mvp.unity";
        private const string RenderPipelinePath = "Assets/Settings/PC_RPAsset.asset";

        /// <summary>
        /// Bind the URP asset to the project. The blank template ships the asset
        /// but leaves the assignment to the user; without it Unity falls back to
        /// the built-in pipeline and every URP shader renders black.
        /// </summary>
        public static void EnsureRenderPipelineAssigned()
        {
            RenderPipelineAsset pipeline = AssetDatabase.LoadAssetAtPath<RenderPipelineAsset>(RenderPipelinePath);
            if (pipeline == null)
            {
                Debug.LogWarning($"[VRAR] render pipeline asset not found at {RenderPipelinePath}");
                return;
            }

            if (GraphicsSettings.defaultRenderPipeline != pipeline)
            {
                GraphicsSettings.defaultRenderPipeline = pipeline;
                Debug.Log($"[VRAR] assigned {pipeline.name} as the default render pipeline");
            }

            QualitySettings.renderPipeline = pipeline;
            AssetDatabase.SaveAssets();
        }

        [MenuItem("VRAR/PoC/Build MVP Scene")]
        public static void BuildFromMenu()
        {
            GameObject root = Build();
            string path = Save();
            Selection.activeGameObject = root;
            Debug.Log($"[VRAR] MVP scene written to {path}");
        }

        /// <summary>Batchmode entry point: build and save the scene, then quit.</summary>
        public static void BuildFromCommandLine()
        {
            Build();
            Save();
            Debug.Log("[VRAR] MVP scene built from command line.");
            EditorApplication.Exit(0);
        }

        public static GameObject Build()
        {
            EnsureRenderPipelineAssigned();

            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            BuildEnvironment();
            BuildGround();
            TurbineRig rig = TurbineFactory.Build();
            rig.transform.position = Vector3.zero;

            GameObject bootstrap = new GameObject("MvpBootstrap");
            bootstrap.AddComponent<MvpBootstrap>();

            BuildViewer();

            EditorSceneManager.MarkSceneDirty(scene);
            return bootstrap;
        }

        public static string Save()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(ScenePath)!);
            EditorSceneManager.SaveScene(SceneManager.GetActiveScene(), ScenePath);
            AddToBuildSettings();
            AssetDatabase.Refresh();
            return ScenePath;
        }

        /// <summary>
        /// Put the PoC scene first in the build list. PlayMode tests load it by
        /// name, and it is the scene the desktop build opens.
        /// </summary>
        public static void AddToBuildSettings()
        {
            var scenes = new System.Collections.Generic.List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            scenes.RemoveAll(scene => scene.path == ScenePath);

            scenes.Insert(0, new EditorBuildSettingsScene(ScenePath, enabled: true));
            EditorBuildSettings.scenes = scenes.ToArray();
        }

        private static void BuildEnvironment()
        {
            GameObject lightObject = new GameObject("Directional Light");
            Light light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.6f;
            light.color = new Color(1f, 0.97f, 0.9f);
            // Light from behind the default camera so the avatars read front-on.
            lightObject.transform.rotation = Quaternion.LookRotation(
                new Vector3(0f, 80f, 0f) - new Vector3(220f, 260f, 240f), Vector3.up);

            GameObject fillObject = new GameObject("Fill Light");
            Light fill = fillObject.AddComponent<Light>();
            fill.type = LightType.Directional;
            fill.intensity = 0.5f;
            fill.color = new Color(0.72f, 0.82f, 1f);
            fillObject.transform.rotation = Quaternion.LookRotation(
                new Vector3(0f, 80f, 0f) - new Vector3(-240f, 140f, -180f), Vector3.up);

            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.46f, 0.51f, 0.58f);
            RenderSettings.ambientEquatorColor = new Color(0.30f, 0.31f, 0.32f);
            RenderSettings.ambientGroundColor = new Color(0.14f, 0.15f, 0.15f);
        }

        /// <summary>
        /// The desktop viewer: a free-fly rig with the camera parented to its head,
        /// standing on the ground at a distance that frames the whole machine. The
        /// turbine is 142 m from tower foot to blade tip, so anything closer crops
        /// the rotor out of frame.
        /// </summary>
        public static GameObject BuildViewer()
        {
            GameObject rig = new GameObject("DesktopRig");
            var hmd = rig.AddComponent<SimulatedHmdRig>();

            var head = new GameObject("Head");
            head.transform.SetParent(rig.transform, false);
            head.transform.localPosition = new Vector3(0f, hmd.Height, 0f);
            hmd.Head = head.transform;

            var cameraObject = new GameObject("PlayerCamera") { tag = "MainCamera" };
            cameraObject.transform.SetParent(head.transform, false);

            Camera camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.55f, 0.68f, 0.82f);
            camera.fieldOfView = 60f;
            camera.nearClipPlane = 0.1f;
            camera.farClipPlane = 4000f;
            cameraObject.AddComponent<AudioListener>();

            FrameViewer(rig, camera);
            return rig;
        }

        /// <summary>
        /// Stand the viewer where the whole turbine is in frame.
        ///
        /// The distance is solved numerically rather than estimated: from eye
        /// height the machine subtends a small angle near the top of the frame and
        /// a much larger one at the bottom, so a closed-form half-span/tan(fov)
        /// figure overshoots badly. The solver walks in until the tower foot to
        /// blade-tip span reaches <see cref="TargetFill"/> of the vertical field of
        /// view, then checks the rotor still fits horizontally at a 4:3 window —
        /// the narrowest we expect.
        /// </summary>
        public static void FrameViewer(GameObject rig, Camera camera = null)
        {
            float bladeTip = TurbineFactory.HubHeight + 1.5f + TurbineFactory.RotorRadius;
            float fov = camera != null ? camera.fieldOfView : DefaultFov;
            var focus = new Vector3(0f, bladeTip * 0.48f, 0f);

            float distance = SolveFramingDistance(bladeTip, fov);
            if (!RotorFitsHorizontally(distance, fov))
            {
                distance = TurbineFactory.RotorRadius /
                           Mathf.Tan(HorizontalFov(fov, ConservativeAspect) * 0.5f * Mathf.Deg2Rad) * 1.15f;
            }

            // Three-quarter view from the lit side, standing on the ground.
            var direction = new Vector3(0.56f, 0f, 0.83f).normalized;
            Vector3 feet = focus + direction * distance;
            rig.transform.position = new Vector3(feet.x, 0f, feet.z);

            Vector3 eye = rig.transform.position + Vector3.up * ViewerEyeHeight;
            rig.transform.rotation = Quaternion.LookRotation((focus - eye).normalized, Vector3.up);
        }

        /// <summary>Distance at which the machine spans <c>TargetFill</c> of the frame height.</summary>
        private static float SolveFramingDistance(float bladeTip, float fov)
        {
            float target = fov * TargetFill;
            float low = 40f;
            float high = 2000f;

            for (int i = 0; i < 48; i++)
            {
                float mid = (low + high) * 0.5f;

                // The top extreme is not the tip directly overhead: a blade can
                // point up *and* toward the viewer, which puts its tip a rotor
                // radius nearer the camera and therefore higher in frame. Framing
                // on the far tip alone crops the rotor as it comes round.
                float top = Mathf.Atan2(bladeTip - ViewerEyeHeight, Mathf.Max(1f, mid - TurbineFactory.RotorRadius));
                float bottom = Mathf.Atan2(-ViewerEyeHeight, mid);

                if ((top - bottom) * Mathf.Rad2Deg > target)
                {
                    low = mid;
                }
                else
                {
                    high = mid;
                }
            }

            return (low + high) * 0.5f;
        }

        private static bool RotorFitsHorizontally(float distance, float fov)
        {
            float halfWidth = distance * Mathf.Tan(HorizontalFov(fov, ConservativeAspect) * 0.5f * Mathf.Deg2Rad);
            return halfWidth > TurbineFactory.RotorRadius * 1.15f;
        }

        private static float HorizontalFov(float verticalFov, float aspect)
        {
            return 2f * Mathf.Atan(Mathf.Tan(verticalFov * 0.5f * Mathf.Deg2Rad) * aspect) * Mathf.Rad2Deg;
        }

        private const float DefaultFov = 60f;
        private const float TargetFill = 0.70f;
        private const float ConservativeAspect = 4f / 3f;
        private const float ViewerEyeHeight = 1.7f;

        /// <summary>
        /// Park the viewer at the drive train. The default view frames the whole
        /// machine, which is the right thing to fly in from; the avatars are a few
        /// metres wide, so documentation shots need the camera flown to them.
        /// </summary>
        public static void FrameViewerOnNacelle(GameObject rig)
        {
            var focus = new Vector3(0f, TurbineFactory.HubHeight + 2.2f, 1.2f);
            // From behind the rotor: looking forward would put a 60 m blade
            // between the camera and the drive train, whatever the rotor azimuth.
            var offset = new Vector3(0.45f, 0.16f, -0.88f).normalized * 30f;
            rig.transform.position = focus + offset;
            rig.transform.rotation = Quaternion.LookRotation((focus - rig.transform.position).normalized, Vector3.up);
        }

        /// <summary>Re-frame the scene's viewer without rebuilding the whole scene.</summary>
        [MenuItem("VRAR/PoC/Frame Camera On Turbine")]
        public static void FrameViewerFromMenu()
        {
            SimulatedHmdRig viewer = Object.FindFirstObjectByType<SimulatedHmdRig>();
            if (viewer == null)
            {
                Debug.LogWarning("[VRAR] no DesktopRig in the open scene");
                return;
            }

            Camera camera = Camera.main;
            FrameViewer(viewer.gameObject, camera);
            EditorSceneManager.MarkSceneDirty(viewer.gameObject.scene);
            Debug.Log($"[VRAR] viewer re-framed at {viewer.transform.position}");
        }

        private static void BuildGround()
        {
            TurbineFactory.BuildGround();
        }
    }
}