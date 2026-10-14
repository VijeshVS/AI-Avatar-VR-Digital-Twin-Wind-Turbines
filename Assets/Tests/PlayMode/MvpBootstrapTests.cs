using System.Collections;
using System.IO;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Vrar.Bootstrap;
using Vrar.Telemetry;
using Vrar.Turbine;

namespace Vrar.Tests
{
    /// <summary>
    /// The wiring test: a bootstrap builds its own rig, feeds it replayed
    /// telemetry and leaves the avatars coloured. This is the loop the PoC
    /// exists to prove, minus the network.
    /// </summary>
    public class MvpBootstrapTests
    {
        private GameObject _bootstrapObject;

        [TearDown]
        public void TearDown()
        {
            if (_bootstrapObject != null)
            {
                Object.Destroy(_bootstrapObject);
            }

            // The bootstrap builds its rig at the scene root, so clean up whatever
            // it left behind or the next test would find it instead of building one.
            foreach (TurbineRig rig in Object.FindObjectsByType<TurbineRig>())
            {
                Object.Destroy(rig.gameObject);
            }
        }

        [UnityTest]
        public IEnumerator BootstrapBuildsARigAndDrivesItFromTelemetry()
        {
            MvpBootstrap bootstrap = CreateBootstrap();
            Assert.That(bootstrap.Rig, Is.Not.Null, "the bootstrap should build a rig when none exists");

            ReplayTelemetrySource replay = Configure(bootstrap, LoadSampleFrames());

            yield return PumpUntil(bootstrap, replay, 2);

            Assert.That(bootstrap.LastFrame, Is.Not.Null, "the client should have received a frame");
            Assert.That(bootstrap.Connected, Is.True);

            Avatar.ComponentAvatar gearbox = bootstrap.Rig.Avatar("gearbox");
            Assert.That(gearbox.Health,
                Is.EqualTo(bootstrap.LastFrame.Component("gearbox").health).Within(1e-4f),
                "the avatar must mirror the frame it was handed");
        }

        [UnityTest]
        public IEnumerator OfflineModeKeepsTheMachineGreen()
        {
            MvpBootstrap bootstrap = CreateBootstrap();
            TelemetryFrame healthy = LoadSampleFrames()[0];
            ReplayTelemetrySource replay = Configure(bootstrap, new[] { healthy });

            yield return PumpUntil(bootstrap, replay, 1);

            Assert.That(bootstrap.LastFrame, Is.Not.Null);
            Assert.That(bootstrap.Rig.WorstHealth(), Is.GreaterThan(0.9f));
        }

        [UnityTest]
        public IEnumerator AFaultedFrameReachesTheAvatarAsAFailingPart()
        {
            TelemetryFrame[] frames = LoadSampleFrames();
            TelemetryFrame degraded = frames[frames.Length - 1];

            MvpBootstrap bootstrap = CreateBootstrap();
            ReplayTelemetrySource replay = Configure(bootstrap, new[] { degraded });

            yield return PumpUntil(bootstrap, replay, 1);

            Avatar.ComponentAvatar gearbox = bootstrap.Rig.Avatar("gearbox");
            Avatar.ComponentAvatar generator = bootstrap.Rig.Avatar("generator");

            Assert.That(gearbox.Health, Is.LessThan(0.6f), "the gearbox must be failing");
            Assert.That(generator.Health, Is.GreaterThan(0.9f), "the generator is not the faulty part");
            Assert.That(gearbox.CurrentColor.r, Is.GreaterThan(gearbox.CurrentColor.g));
        }

        private MvpBootstrap CreateBootstrap()
        {
            _bootstrapObject = new GameObject("Bootstrap");
            MvpBootstrap bootstrap = _bootstrapObject.AddComponent<MvpBootstrap>();

            // Freeze polling before it can fire a real HTTP request at a service
            // that is not running, then take manual control of the source.
            SetPrivateField(bootstrap, "_playing", false);
            return bootstrap;
        }

        private static ReplayTelemetrySource Configure(MvpBootstrap bootstrap, TelemetryFrame[] frames)
        {
            var replay = new ReplayTelemetrySource(frames);
            SetPrivateField(bootstrap, "_pollIntervalSeconds", 0f);
            SetPrivateField(bootstrap, "_source", replay);
            SetPrivateField(bootstrap, "_playing", true);
            return replay;
        }

        /// <summary>
        /// Advance frames until the replay has been consumed. The pump stops on the
        /// frame the last request lands on: the replay wraps, so waiting for
        /// "at least N" could silently roll back to a healthy frame.
        /// </summary>
        private static IEnumerator PumpUntil(MvpBootstrap bootstrap, ReplayTelemetrySource replay, int count)
        {
            int target = replay.Cursor + count - 1;
            for (int i = 0; i < 120 && replay.Cursor <= target; i++)
            {
                yield return null;
            }

            Assert.That(replay.Cursor, Is.EqualTo(target + 1), "the client did not poll as expected");
        }

        private static TelemetryFrame[] LoadSampleFrames()
        {
            string path = Path.Combine(Application.streamingAssetsPath, "telemetry_sample.json");
            Assert.That(File.Exists(path), Is.True, $"missing {path}; run `uv run python -m telemetry.export_sample`");
            return SampleFrames.Parse(File.ReadAllText(path));
        }

        private static void SetPrivateField(object target, string fieldName, object value)
        {
            System.Reflection.FieldInfo field = target.GetType()
                .GetField(fieldName, System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            Assert.That(field, Is.Not.Null, $"no field '{fieldName}' on {target.GetType().Name}");
            field.SetValue(target, value);
        }
    }
}