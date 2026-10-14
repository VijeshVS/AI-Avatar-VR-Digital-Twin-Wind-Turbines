using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEngine.TestTools;
using Vrar.Telemetry;
using Vrar.Turbine;

namespace Vrar.Tests
{
    /// <summary>
    /// Regression guard for the scene path. A rig built in the Editor keeps its
    /// avatar index and rotor references in plain C# collections, which are not
    /// serialised: loading the scene from disk used to give a rig that silently
    /// dropped every telemetry frame.
    /// </summary>
    public class SceneRigTests
    {
        private const string SceneName = "Mvp";

        [UnityTest]
        public IEnumerator SceneLoadedRigResolvesAndAppliesFrames()
        {
            yield return LoadMvpScene();

            TurbineRig rig = Object.FindFirstObjectByType<TurbineRig>();
            Assert.That(rig, Is.Not.Null, "the PoC scene should contain a turbine rig");
            Assert.That(rig.Avatars.Count, Is.EqualTo(5), "a loaded rig must resolve its avatars");
            Assert.That(rig.Rotor, Is.Not.Null, "a loaded rig must resolve its rotor");

            foreach (string id in new[] { "blade_set", "main_bearing", "gearbox", "generator", "pitch_system" })
            {
                Assert.That(rig.Avatar(id), Is.Not.Null, $"loaded rig has no avatar for '{id}'");
            }

            string sample = File.ReadAllText(Path.Combine(Application.streamingAssetsPath, "telemetry_sample.json"));
            TelemetryFrame[] frames = SampleFrames.Parse(sample);
            TelemetryFrame degraded = frames[frames.Length - 1];

            rig.Apply(degraded);
            yield return null;

            Assert.That(rig.Avatar("gearbox").Health, Is.EqualTo(degraded.Component("gearbox").health).Within(1e-4f),
                "a scene-loaded rig must apply frames, not drop them");
            Assert.That(rig.Avatar("gearbox").Health, Is.LessThan(0.6f));
            Assert.That(rig.Rotor.localRotation, Is.Not.EqualTo(Quaternion.identity).Within(1f));
        }

        /// <summary>
        /// The scene's default view must show the whole machine. Reported as "I
        /// cannot see the complete wind turbine": a camera left at a nacelle
        /// close-up, or one whose framing pitch gets flattened to the horizon by
        /// the fly rig, crops the rotor out of frame.
        /// </summary>
        [UnityTest]
        public IEnumerator DefaultCameraFramesTheWholeMachine()
        {
            yield return LoadMvpScene();
            yield return null;

            Camera camera = Camera.main;
            Assert.That(camera, Is.Not.Null, "the PoC scene needs a camera tagged MainCamera");

            Vector3 min = new Vector3(-TurbineFactory.RotorRadius, 0f, -TurbineFactory.RotorRadius);
            float tip = TurbineFactory.HubHeight + 1.5f + TurbineFactory.RotorRadius;
            Vector3 max = new Vector3(TurbineFactory.RotorRadius, tip, TurbineFactory.RotorRadius);

            for (int i = 0; i < 8; i++)
            {
                var corner = new Vector3(
                    (i & 1) == 0 ? min.x : max.x,
                    (i & 2) == 0 ? min.y : max.y,
                    (i & 4) == 0 ? min.z : max.z);

                Vector3 viewport = camera.WorldToViewportPoint(corner);
                Assert.That(viewport.z, Is.GreaterThan(0f), $"corner {corner} is behind the camera");
                Assert.That(viewport.x, Is.InRange(-0.02f, 1.02f), $"corner {corner} is cropped horizontally");
                Assert.That(viewport.y, Is.InRange(-0.02f, 1.02f), $"corner {corner} is cropped vertically");
            }
        }

        /// <summary>
        /// The fly rig rebuilds its rotation every frame from yaw/pitch, so it has
        /// to start from the authored view. When it did not, the camera snapped to
        /// the horizon and everything above the frame centre was lost.
        /// </summary>
        [UnityTest]
        public IEnumerator FlyRigPreservesTheAuthoredViewAngle()
        {
            yield return LoadMvpScene();
            yield return null;

            Camera camera = Camera.main;
            Assert.That(camera, Is.Not.Null);

            // The authored framing looks up at the machine from the ground.
            Assert.That(camera.transform.forward.y, Is.GreaterThan(0.05f),
                "the rig flattened the view to the horizon and cropped the rotor");
        }

        private static IEnumerator LoadMvpScene()
        {
            string path = Path.Combine(Application.dataPath, "Scenes/Mvp/Mvp.unity");
            Assert.That(File.Exists(path), Is.True, $"missing {path}; run VRAR/PoC/Build MVP Scene");

            yield return SceneManager.LoadSceneAsync(SceneName, LoadSceneMode.Single);
            yield return null;

            // The scene ships a live bootstrap; stop it so it cannot overwrite the
            // frames these tests drive by hand.
            foreach (Vrar.Bootstrap.MvpBootstrap bootstrap in Object.FindObjectsByType<Vrar.Bootstrap.MvpBootstrap>())
            {
                Object.Destroy(bootstrap.gameObject);
            }

            yield return null;
        }
    }
}