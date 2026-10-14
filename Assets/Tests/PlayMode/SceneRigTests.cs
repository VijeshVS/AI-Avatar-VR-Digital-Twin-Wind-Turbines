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
            string path = Path.Combine(Application.dataPath, "Scenes/Mvp/Mvp.unity");
            Assert.That(File.Exists(path), Is.True, $"missing {path}; run VRAR/PoC/Build MVP Scene");

            yield return SceneManager.LoadSceneAsync(SceneName, LoadSceneMode.Single);
            yield return null;

            TurbineRig rig = Object.FindFirstObjectByType<TurbineRig>();
            Assert.That(rig, Is.Not.Null, "the PoC scene should contain a turbine rig");
            Assert.That(rig.Avatars.Count, Is.EqualTo(5), "a loaded rig must resolve its avatars");
            Assert.That(rig.Rotor, Is.Not.Null, "a loaded rig must resolve its rotor");

            foreach (string id in new[] { "blade_set", "main_bearing", "gearbox", "generator", "pitch_system" })
            {
                Assert.That(rig.Avatar(id), Is.Not.Null, $"loaded rig has no avatar for '{id}'");
            }

            // The scene ships a live bootstrap; stop it so it cannot overwrite the
            // frame this test drives by hand.
            foreach (Vrar.Bootstrap.MvpBootstrap bootstrap in Object.FindObjectsByType<Vrar.Bootstrap.MvpBootstrap>())
            {
                Object.Destroy(bootstrap.gameObject);
            }

            yield return null;

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
    }
}