using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Vrar.Presentation;

namespace Vrar.Tests
{
    /// <summary>
    /// The auto-flight that focus mode drives the camera with. It moves the rig
    /// rather than teleporting it, so these assert convergence and aim, not an
    /// instantaneous position.
    /// </summary>
    public class FocusFlightTests
    {
        private GameObject _rigObject;

        [TearDown]
        public void TearDown()
        {
            if (_rigObject != null)
            {
                Object.Destroy(_rigObject);
            }
        }

        private SimulatedHmdRig CreateRig()
        {
            _rigObject = new GameObject("DesktopRig");
            // RequireComponent supplies the CharacterController the rig flies with.
            return _rigObject.AddComponent<SimulatedHmdRig>();
        }

        [Test]
        public void DoesNotAutoFlyUntilAsked()
        {
            SimulatedHmdRig rig = CreateRig();

            Assert.IsFalse(rig.IsAutoFlying);
        }

        [Test]
        public void AutoFlyToTakesControlAndEndAutoFlyReleasesIt()
        {
            SimulatedHmdRig rig = CreateRig();

            rig.AutoFlyTo(new Vector3(0f, 0f, 10f), new Vector3(0f, 80f, 0f));
            Assert.IsTrue(rig.IsAutoFlying);

            rig.EndAutoFly();
            Assert.IsFalse(rig.IsAutoFlying);
        }

        [UnityTest]
        public IEnumerator AutoFlightConvergesOnTheTargetPosition()
        {
            SimulatedHmdRig rig = CreateRig();
            rig.transform.position = new Vector3(0f, 0f, 0f);
            var target = new Vector3(0f, 0f, 30f);

            rig.AutoFlyTo(target, target + Vector3.forward);
            yield return WaitFor(() => Vector3.Distance(rig.transform.position, target) < 0.5f);

            Assert.Less(Vector3.Distance(rig.transform.position, target), 0.5f);
        }

        [UnityTest]
        public IEnumerator AutoFlightAimsAtTheLookPoint()
        {
            SimulatedHmdRig rig = CreateRig();
            rig.transform.position = new Vector3(0f, 0f, 0f);
            // Straight up: exercises the pitch path, which is where a look-at
            // built from forward alone tends to break.
            var lookAt = new Vector3(0f, 90f, 0f);

            rig.AutoFlyTo(new Vector3(0f, 0f, 40f), lookAt);
            yield return WaitFor(() => Mathf.Abs(rig.EyePosition.y - 80f) < 3f);
            yield return null;

            Vector3 toTarget = (lookAt - rig.EyePosition).normalized;
            Vector3 forward = rig.transform.forward;
            Assert.Greater(Vector3.Dot(forward, toTarget), 0.95f);
        }

        [UnityTest]
        public IEnumerator ReissuingTheTargetKeepsRetargeting()
        {
            SimulatedHmdRig rig = CreateRig();
            rig.transform.position = Vector3.zero;
            var first = new Vector3(0f, 0f, 20f);
            var second = new Vector3(0f, 0f, 60f);

            rig.AutoFlyTo(first, first);
            yield return null;
            rig.AutoFlyTo(second, second);
            yield return WaitFor(() => Vector3.Distance(rig.transform.position, second) < 0.5f);

            // The rig must have followed the second target, not parked on the first.
            Assert.Less(Vector3.Distance(rig.transform.position, second), 0.5f);
        }

        /// <summary>Yield frames until <paramref name="done"/> holds or the budget runs out.</summary>
        private static IEnumerator WaitFor(System.Func<bool> done)
        {
            for (int i = 0; i < 400 && !done(); i++)
            {
                yield return null;
            }
        }
    }
}