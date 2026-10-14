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
            bootstrap.AddComponent<SimulatedHmdRig>();

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
            GameObject cameraObject = new GameObject("Main Camera") { tag = "MainCamera" };
            Camera camera = cameraObject.AddComponent<Camera>();
            cameraObject.AddComponent<AudioListener>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.55f, 0.68f, 0.82f);
            // Framed on the nacelle: that is where the avatars live. Pull back
            // with the free-fly rig to see the whole machine.
            cameraObject.transform.position = new Vector3(15f, 88f, 24f);
            cameraObject.transform.LookAt(new Vector3(0f, 82f, 1f));
            camera.fieldOfView = 50f;

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

        private static void BuildGround()
        {
            TurbineFactory.BuildGround();
        }
    }
}